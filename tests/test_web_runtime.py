"""Generic hosted-app security helpers."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sopilot.web_runtime import install_api_security


def test_install_api_security_allows_health_and_blocks_api(monkeypatch):
    monkeypatch.setenv("SOPILOT_APP_TOKEN", "token-123")
    app = FastAPI()
    install_api_security(app)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/private")
    def private():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/private").status_code == 401
    assert client.get("/api/private", headers={"x-app-token": "token-123"}).status_code == 200


def test_install_api_security_requires_trial_code_for_protected_api(monkeypatch):
    monkeypatch.setenv("SOPILOT_APP_TOKEN", "token-123")
    monkeypatch.setenv("SOPILOT_TRIAL_CODE", "invite-123")
    app = FastAPI()
    install_api_security(app, access_code_env="SOPILOT_TRIAL_CODE")

    @app.get("/api/auth/check")
    def auth_check():
        return {"ok": True}

    @app.get("/api/private")
    def private():
        return {"ok": True}

    client = TestClient(app)
    token_header = {"x-app-token": "token-123"}
    assert client.get("/api/auth/check", headers=token_header).status_code == 200
    assert client.get("/api/private", headers=token_header).status_code == 401
    assert (
        client.get(
            "/api/private",
            headers={**token_header, "x-trial-code": "invite-123"},
        ).status_code
        == 200
    )
