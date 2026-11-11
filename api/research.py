"""Verdict Research — Vercel Python Function
    Single Python Function handling all research endpoints,
    deployed on Vercel. Replaces the Flask server (backend/web.py).

    Routes (routed via vercel.json /api/(.*) → api/research.py):
        POST  /api/research          — Start product research
        GET   /api/status            — Check backend readiness
        GET   /api/jobs/{job_id}     — Poll job progress and results
"""

from __future__ import annotations

import os
import sys
import json
import logging
import uuid
from typing import Optional, Any, Dict

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import supabase
from supabase import create_client, Client

# --- FastAPI App ---
app = FastAPI(
    title="Verdict Research API",
    description="Research API for the Verdict SaaS platform, deployed on Vercel",
    version="1.0.0",
)

# --- Supabase Configuration ---
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_SERVICE_ROLE_KEY must be set for the Vercel Python function."
    )

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- Research Pipeline Imports ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.pipeline import ResearchRequest, run_research

# --- Helper: Extract user ID from Supabase JWT token ---

def _extract_user_id(token: str) -> Optional[str]:
    """Extract the user ID from a Supabase auth JWT token.
    The JWT payload has a 'sub' field that corresponds to auth.users.id.
    """
    try:
        import base64
        payload = token.split(".")[1] if "." in token else ""
        decoded = base64.urlsafe_b64decode(payload + "==").decode("utf-8")
        data = json.loads(decoded)
        return data.get("sub")
    except Exception:
        return None

# --- Progress Callback that writes to Supabase ---

class SupabaseProgressCallback:
    """Callable wrapper that reports research progress to Supabase.

    Stores each progress step in the research_jobs table so the frontend
    can poll and display live progress.
    """

    def __init__(self, job_id: str, sb_client: Client) -> None:
        self.job_id = job_id
        self.sb = sb_client
        self.steps: list[str] = []
        self._batch_count = 0

    def __call__(self, message: str) -> None:
        """Called by the research pipeline to report progress."""
        self.steps.append(message)
        self._batch_count += 1
        # Batch updates: write to Supabase every 5 steps
        if self._batch_count >= 5:
            try:
                self.sb.table("research_jobs").update(
                    {"progress": self.steps, "updated_at": "now()"}
                ).eq("id", self.job_id).execute()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Failed to update progress in Supabase: %s", e
                )
            self.steps = []
            self._batch_count = 0

    def flush(self) -> None:
        """Flush any remaining steps to Supabase."""
        if self.steps:
            try:
                self.sb.table("research_jobs").update(
                    {"progress": self.steps, "updated_at": "now()"}
                ).eq("id", self.job_id).execute()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Failed to flush progress in Supabase: %s", e
                )


# --- Dependency: Get current settings ---

def _get_current_settings() -> Settings:
    """Build Settings from environment variables available at runtime."""
    from verdict.config import Settings as SettingsClass

    return SettingsClass.from_env(
        oxylabs_api_key=os.getenv("OXYLABS_API_KEY", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        nvidia_api_key=os.getenv("NVIDIA_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        models=os.getenv("OPENROUTER_MODELS", ""),
    )


# --- Auth helper ---

def _get_user_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """Extract user info from the Supabase auth token in the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.replace("Bearer ", "").strip()
    try:
        user_data = sb.auth.get_user(token)
        if hasattr(user_data, "user") and user_data.user:
            return {
                "id": user_data.user.id,
                "email": user_data.user.email,
                "user_metadata": user_data.user.user_metadata,
            }
    except Exception:
        pass
    # Also try direct decode
    try:
        user_id = _extract_user_id(token)
        if user_id:
            # Get user by ID
            user_resp = sb.table("users").select("*").eq("id", user_id).single().execute()
            if user_resp.data:
                return {"id": user_id, "email": "", "user_metadata": {}}
    except Exception:
        pass
    return None


# --- API Routes ---

@app.post("/api/research")
async def start_research(request: Request) -> Response:
    """Start a new research job.

    Expects JSON body with research parameters.
    Returns the job ID immediately; the frontend polls for progress.
    """
    # --- Auth check ---
    user_info = _get_user_from_request(request)
    if not user_info:
        return JSONResponse(status_code=401, content={"error": "Please log in to run research."})
    user_id = user_info["id"]

    # --- Parse request body ---
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON payload."})

    text = str(payload.get("text", "")).strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "Paste a product URL."})

    keywords = str(payload.get("keywords", "")).strip()
    focus = str(payload.get("focus", "")).strip()
    engine = str(payload.get("engine", "yahoo")).strip().lower()
    render = bool(payload.get("render", False))
    no_ai = bool(payload.get("no_ai", False))

    # --- Validate input ---
    if not text:
        return JSONResponse(status_code=400, content={"error": "Paste a product URL."})

    # --- Check for duplicate active jobs for this user ---
    try:
        existing = (
            sb.table("research_jobs")
            .select("id, status")
            .eq("user_id", user_id)
            .in_("status", ["queued", "running", "timeout"])
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            # Return the existing active job
            job = existing.data[0]
            return JSONResponse(
                status_code=202,
                content={"id": job["id"], "status": job["status"], "note": "Existing job resumed."},
            )
    except Exception as e:
        logging.getLogger(__name__).warning("Duplicate job check failed: %s", e)

    # --- Create job in Supabase ---
    job_id = uuid4().hex
    try:
        sb.table("research_jobs").insert(
            {
                "id": job_id,
                "user_id": user_id,
                "status": "queued",
                "progress": [],
                "result": {"title": "", "markdown": "", "sources": [], "models": []},
                "error": "",
            }
        ).execute()
    except Exception as e:
        logging.getLogger(__name__).error("Failed to create research job: %s", e)
        return JSONResponse(status_code=500, content={"error": "Failed to create research job."})

    # --- Run the research pipeline ---
    try:
        settings = _get_current_settings()

        # Create progress callback that writes to Supabase
        progress_cb = SupabaseProgressCallback(job_id, sb)

        # Build ResearchRequest from payload
        req = ResearchRequest(
            text=text,
            keywords=keywords if keywords else "",
            focus=focus if focus else "",
            engine=engine if engine else "yahoo",
            render=render,
            no_ai=no_ai,
        )

        # Run the research pipeline.
        # This is a blocking call. It may take longer than the Vercel function
        # timeout, in which case the function will be terminated but the job
        # record in Supabase will persist with whatever progress was made.
        try:
            result: Any = run_research(req, settings, progress_cb)
        except VerdictError as e:
            # Expected validation errors
            progress_cb.flush()
            sb.table("research_jobs").update(
                {"status": "error", "error": str(e)}
            ).eq("id", job_id).execute()
            return JSONResponse(status_code=400, content={"error": str(e)})
        except Exception as e:
            # Unexpected errors - never leak internals to the browser
            progress_cb.flush()
            sb.table("research_jobs").update(
                {"status": "error", "error": "Something went wrong while researching. Please try again."}
            ).eq("id", job_id).execute()
            logging.getLogger(__name__).exception("Research job %s crashed", job_id)
            return JSONResponse(
                status_code=500,
                content={"error": "Something went wrong while researching. Please try again."},
            )

        # --- Job completed successfully ---
        # Build the result data for Supabase
        sources_data = result.sources if hasattr(result, "sources") else []
        models_data = result.models if hasattr(result, "models") else []

        # Convert sources to serializable format
        sources_serializable = []
        for s in (sources_data if isinstance(sources_data, list) else []):
            sources_serializable.append(
                {
                    "title": s.title if hasattr(s, "title") else str(s.get("title", "")),
                    "url": s.url if hasattr(s, "url") else str(s.get("url", "")),
                    "error": s.error if hasattr(s, "error") else "",
                }
            )

        result_data = {
            "title": result.title if hasattr(result, "title") else "",
            "markdown": result.markdown if hasattr(result, "markdown") else "",
            "sources": sources_serializable,
            "models": models_data if isinstance(models_data, list) else [],
        }

        # Update job in Supabase as done
        sb.table("research_jobs").update(
            {
                "status": "done",
                "result": result_data,
                "error": "",
                "updated_at": "now()",
            }
        ).eq("id", job_id).execute()

        return JSONResponse(
            status_code=202,
            content={"id": job_id, "status": "done", "result": result_data},
        )

    except Exception as e:
        # Catch-all if something goes wrong before the pipeline runs
        logging.getLogger(__name__).error("Unexpected error in research start: %s", e, exc_info=True)
        # Try to update job status if it was created
        if "job_id" in dir():
            try:
                sb.table("research_jobs").update(
                    {"status": "error", "error": "Internal server error."}
                ).eq("id", job_id).execute()
            except Exception:
                pass
        return JSONResponse(status_code=500, content={"error": "Internal server error."})


@app.get("/api/status")
async def get_status() -> Response:
    """Check backend readiness.

    Returns whether the scraper and AI keys are configured.
    """
    from verdict.llm import ai_available
    from verdict.config import Settings as SettingsClass

    settings = _get_current_settings()

    # Check Oxylabs key
    oxylabs_ready = bool(settings.oxylabs_api_key)

    # Check AI availability
    ai_ready = ai_available(settings)

    return JSONResponse(
        status_code=200,
        content={
            "version": "1.0.0",
            "engines": ["yahoo", "brave", "duckduckgo", "bing", "google"],
            "ai_ready": ai_ready,
            "scrape_ready": oxylabs_ready,
        },
    )


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> Response:
    """Poll a research job for progress and the finished report.

    Users can only access their own jobs (enforced via Supabase auth).
    """
    # --- Auth check ---
    user_info = _get_user_from_request(request)
    if not user_info:
        return JSONResponse(status_code=401, content={"error": "Please log in to run research."})
    user_id = user_info["id"]

    # --- Fetch job from Supabase ---
    try:
        job_resp = sb.table("research_jobs").select("*").eq("id", job_id).single().execute()
    except Exception:
        return JSONResponse(status_code=404, content={"error": "That job expired or doesn't exist."})

    job_data = job_resp.data if job_resp.data else None
    if job_data is None:
        return JSONResponse(status_code=404, content={"error": "That job expired or doesn't exist."})

    # --- Owner authorization check ---
    if job_data.get("user_id") != user_id:
        return JSONResponse(status_code=403, content={"error": "Unauthorized to access this job."})

    # --- Return job data ---
    return JSONResponse(
        status_code=200,
        content={
            "id": job_data["id"],
            "status": job_data["status"],
            "progress": job_data.get("progress", []),
            "result": job_data.get("result", {"title": "", "markdown": "", "sources": [], "models": []}),
            "error": job_data.get("error", ""),
            "created_at": job_data.get("created_at"),
        },
    )