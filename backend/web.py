#!/usr/bin/env python3
"""Verdict Research website (Flask).

    python web.py                 # http://127.0.0.1:5000
    flask --app web run --debug

Jobs run in background threads. The browser starts one with POST /api/research
and polls GET /api/jobs/<id> for progress and the finished report.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request
from markdown_it import MarkdownIt

from verdict import __version__
from verdict.config import Settings
from verdict.llm import ai_available
from verdict.errors import VerdictError
from verdict.pipeline import ResearchRequest, run_research
from verdict.search import ENGINES

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


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.config["SETTINGS"] = settings or Settings.from_env()

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
            app.logger.exception("Research job %s crashed", job.id)
            with job.lock:
                job.error = "Something went wrong while researching. Please try again."
                job.status = "error"
        finally:
            job.finished = time.time()

    @app.get("/")
    def index():
        settings = app.config["SETTINGS"]
        return render_template(
            "index.html",
            version=__version__,
            engines=ENGINES,
            ai_ready=ai_available(settings),
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
            render=bool(payload.get("render")),
            no_ai=bool(payload.get("no_ai")),
        )
        if not req.text.strip():
            return jsonify(error="Paste a product URL."), 400

        job = Job(req)
        with jobs_lock:
            jobs[job.id] = job
        pool.submit(work, job)
        return jsonify(id=job.id), 202

    @app.get("/api/jobs/<job_id>")
    def poll(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return jsonify(error="That job expired or doesn't exist."), 404
        try:
            since = max(0, int(request.args.get("since", 0)))
        except ValueError:
            since = 0
        return jsonify(job.snapshot(since))

    @app.get("/api/status")
    def status():
        settings = app.config["SETTINGS"]
        return jsonify(
            version=__version__,
            engines=list(ENGINES),
            ai_ready=ai_available(settings),
            scrape_ready=bool(settings.oxylabs_api_key),
        )

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
        threaded=True,
    )
