import time

import pytest

import web as web_module
from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.pipeline import ResearchResult


@pytest.fixture()
def client():
    app = web_module.create_app(Settings(oxylabs_api_key="x", openrouter_api_key="y"))
    app.config["TESTING"] = True
    return app.test_client()


def wait_for(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}").get_json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Verdict Research" in res.data


def test_rejects_empty_input(client):
    res = client.post("/api/research", json={"text": "  "})
    assert res.status_code == 400


def test_job_success_reports_progress_and_sanitizes_html(client, monkeypatch):
    def fake(req, settings, progress):
        progress("step one")
        progress("step two")
        return ResearchResult(
            "Widget review",
            "# Widget\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1)) [ok](https://example.com)",
            [{"title": "t", "url": "https://example.com", "partial": False}],
            ["m"],
        )

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post(
        "/api/research", json={"text": "https://shop.example/p"}
    ).get_json()["id"]
    data = wait_for(client, job_id)

    assert data["status"] == "done"
    assert data["steps"] == ["step one", "step two"]
    assert data["title"] == "Widget review"
    assert "<script>" not in data["html"]
    assert "href=\"javascript" not in data["html"]
    assert 'href="https://example.com"' in data["html"]


def test_poll_since_returns_only_new_steps(client, monkeypatch):
    def fake(req, settings, progress):
        for i in range(3):
            progress(f"s{i}")
        return ResearchResult("t", "# t")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://shop.example/p"}).get_json()["id"]
    wait_for(client, job_id)
    data = client.get(f"/api/jobs/{job_id}?since=2").get_json()
    assert data["steps"] == ["s2"]
    assert data["step_count"] == 3


def test_verdict_error_is_shown_to_user(client, monkeypatch):
    def fake(req, settings, progress):
        raise VerdictError("Every page failed")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://a.com"}).get_json()["id"]
    data = wait_for(client, job_id)
    assert data["status"] == "error"
    assert data["error"] == "Every page failed"


def test_unexpected_error_hides_internals(client, monkeypatch):
    def fake(req, settings, progress):
        raise RuntimeError("secret internal detail with key sk-123")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://a.com"}).get_json()["id"]
    data = wait_for(client, job_id)
    assert data["status"] == "error"
    assert "sk-123" not in data["error"]


def test_unknown_job_404(client):
    assert client.get("/api/jobs/doesnotexist").status_code == 404
