"""API smoke tests (no live LLM calls)."""

from fastapi.testclient import TestClient

from polygnosis_api.main import app


client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["protocol"] == "polygnosis-v3"


def test_boardroom_job_not_found():
    r = client.get("/v1/boardroom/does-not-exist")
    assert r.status_code == 404


def test_boardroom_accepts_request(monkeypatch):
    # Prevent background thread from hitting a real LLM
    import polygnosis_api.main as main_mod

    def noop_run(job_id, request):
        main_mod.store.update(
            job_id,
            status=main_mod.JobStatus.completed,
            phase="complete",
            result={
                "job_id": job_id,
                "objective": request.objective,
                "final_output": "ok",
                "scoring_algorithm": "hybrid",
                "trail": [],
            },
        )

    monkeypatch.setattr(main_mod, "_run_boardroom", noop_run)

    r = client.post("/v1/boardroom", json={"objective": "Design a JWT auth middleware"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert "job_id" in body
    assert body["poll_url"] == f"/v1/boardroom/{body['job_id']}"
