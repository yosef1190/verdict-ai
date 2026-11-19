#!/usr/bin/env python3
"""Verdict Research website (Flask).

    python web.py                 # http://127.0.0.1:5000
    flask --app web run --debug

Jobs run in background threads. The browser starts one with POST /api/research
and polls GET /api/jobs/<id> for progress and the finished report.
Supabase is used for job persistence so jobs survive Render free-tier sleeping.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from uuid import uuid4
import logging
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request
from markdown_it import MarkdownIt

from verdict import __version__
from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.pipeline import ResearchRequest, run_research

# "js-default" keeps raw HTML disabled, so scraped or AI text can never inject
# markup, and it refuses javascript: links.
_md = MarkdownIt("js-default", {"linkify": False})

JOB_TTL_SECONDS = 60 * 60  # finished jobs are forgotten after an hour
MAX_STEPS = 200


class Job:
    def __init__(self, req: ResearchRequest) -> None:
        self.id = uuid.uuid4().hex
        self.req = req
        self.status = "queued"  # queued | running | done | error
        self.steps: list[str] = []
        self.error = ""
        self.title = ""
        self.markdown = ""
        self.html = ""
        self.sources: list[dict] = []
        self.models: list[str] = []
        self.created = time.time()
        self.finished: float | None = None
        self.lock = threading.Lock()

    def progress(self, message: str) -> None:
        with self.lock:
            if len(self.steps) < MAX_STEPS:
                self.steps.append(message)

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            data = {
                "id": self.id,
                "status": self.status,
                "steps": self.steps[since:],
                "step_count": len(self.steps),
            }
            if self.status == "error":
                data["error"] = self.error
            if self.status == "done":
                data.update(
                    title=self.title,
                    markdown=self.markdown,
                    html=self.html,
                    sources=self.sources,
                    models=self.models,
                )
            return data


# Supabase client for job persistence
import supabase
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
else:
    sb = None  # type: ignore

logger = logging.getLogger(__name__)


def _supabase_update_job(job_id: str, data: dict) -> None:
    """Update a job in Supabase."""
    if sb is None:
        logger.warning("Supabase not configured, cannot update job %s", job_id)
        return
    try:
        sb.table("research_jobs").update(data).eq("id", job_id).execute()
    except Exception as e:
        logger.warning("Failed to update job %s in Supabase: %s", job_id, e)


def _supabase_get_job(job_id: str) -> dict | None:
    """Get a job from Supabase."""
    if sb is None:
        return None
    try:
        resp = sb.table("research_jobs").select("*").eq("id", job_id).single().execute()
        return resp.data if resp.data else None
    except Exception as e:
        logger.warning("Failed to get job %s from Supabase: %s", job_id, e)
        return None


def _supabase_create_job(job_id: str, user_id: str | None, status: str, progress: list) -> None:
    """Create a new job in Supabase."""
    if sb is None:
        return
    try:
        sb.table("research_jobs").insert(
            {"id": job_id, "user_id": user_id, "status": status, "progress": progress, "error": ""}
        ).execute()
    except Exception as e:
        logger.warning("Failed to create job %s in Supabase: %s", job_id, e)


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.config["SETTINGS"] = settings or Settings.from_env()

    # Job storage: in-memory dict (also synced with Supabase)
    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    max_concurrent = int(os.getenv("VERDICT_WEB_CONCURRENCY", "3") or 3)
    pool = ThreadPoolExecutor(max_workers=max(1, max_concurrent), thread_name_prefix="verdict-job")
    app.config["JOBS"] = jobs
    app.config["POOL"] = pool

    def prune() -> None:
        now = time.time()
        with jobs_lock:
            stale = [
                job_id
                for job_id, job in jobs.items()
                if job.finished and now - job.finished > JOB_TTL_SECONDS
            ]
            for job_id in stale:
                del jobs[job_id]
                # Also remove from Supabase
                if sb is not None:
                    try:
                        sb.table("research_jobs").delete().eq("id", job_id).execute()
                    except Exception:
                        pass

    def work(job: Job) -> None:
        job.status = "running"
        try:
            result = run_research(job.req, app.config["SETTINGS"], job.progress)
            html = _md.render(result.markdown)
            with job.lock:
                job.title = result.title
                job.markdown = result.markdown
                job.html = html
                job.sources = result.sources
                job.models = result.models
                job.status = "done"
        except VerdictError as exc:
            with job.lock:
                job.error = str(exc)
                job.status = "error"
        except Exception:  # never leak internals to the browser
            logger.exception("Research job %s crashed", job.id)
            with job.lock:
                job.error = "Something went wrong while researching. Please try again."
                job.status = "error"
        finally:
            job.finished = time.time()
            # Persist the completed job to Supabase
            if sb is not None:
                try:
                    data: dict = {
                        "status": job.status,
                        "error": job.error,
                        "title": job.title,
                        "markdown": job.markdown,
                        "html": job.html,
                        "sources": job.sources,
                        "models": job.models,
                        "updated_at": "now()",
                    }
                    _supabase_update_job(job.id, data)
                except Exception as e:
                    logger.warning(
                        "Failed to persist job %s to Supabase: %s", job.id, e
                    )

    @app.get("/")
    def index():
        settings = app.config["SETTINGS"]
        return render_template(
            "index.html",
            version=__version__,
            engines=[],
            ai_ready=bool(settings.oxylabs_api_key),
            scrape_ready=bool(settings.oxylabs_api_key),
        )

    @app.post("/api/research")
    def start():
        prune()
        payload = request.get_json(silent=True) or {}
        req = ResearchRequest(
            text=str(payload.get("text") or ""),
            keywords=str(payload.get("keywords") or ""),
            focus=str(payload.get("focus") or ""),
            engine=str(payload.get("engine") or "yahoo"),
            render=bool(payload.get("render", False)),
            no_ai=bool(payload.get("no_ai", False)),
        )
        if not req.text.strip():
            return jsonify(error="Paste a product URL."), 400

        job_id = uuid4().hex
        # Create job in memory and Supabase
        with jobs_lock:
            jobs[job_id] = Job(req)
        _supabase_create_job(job_id, None, "queued", [])

        # Run the research pipeline in a background thread
        pool.submit(work, jobs[job_id])
        return jsonify(id=job_id), 202

    @app.get("/api/jobs/<job_id>")
    def poll(job_id: str):
        # First check in-memory jobs
        with jobs_lock:
            job = jobs.get(job_id)

        if job is not None:
            try:
                since = max(0, int(request.args.get("since", 0)))
            except ValueError:
                since = 0
            return jsonify(job.snapshot(since))

        # Fall back to Supabase
        job_data = _supabase_get_job(job_id)
        if job_data is not None:
            # Build a minimal response from Supabase data
            status = job_data.get("status", "queued")
            steps = job_data.get("progress", [])
            result = job_data.get("result", {}) or {}
            return jsonify(
                id=job_data["id"],
                status=status,
                steps=steps,
                step_count=len(steps),
                result=result,
                error=job_data.get("error", ""),
                created_at=job_data.get("created_at"),
            )

        return jsonify(error="That job expired or doesn't exist."), 404

    @app.get("/api/status")
    def status():
        settings = app.config["SETTINGS"]
        from verdict.llm import ai_available
        return jsonify(
            version=__version__,
            engines=["yahoo", "brave", "duckduckgo", "bing", "google"],
            ai_ready=ai_available(settings),
            scrape_ready=bool(settings.oxylabs_api_key),
        )

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    return app


app = create_app()

if __name__ == "__main__":
    # Render provides $PORT; bind to 0.0.0.0 for external access
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)