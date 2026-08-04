import os
from urllib.parse import parse_qs, urlparse

os.environ["GITHUB_CLIENT_ID"] = "test-client-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-client-secret"

from fastapi.testclient import TestClient

from backend.app.api import auth as auth_module
from backend.app.config import get_settings
from backend.app.main import app
from backend.app.services.github import GitHubClient


def _state_from_login_url(login_url: str) -> str:
    query = parse_qs(urlparse(login_url).query)
    return query["state"][0]


def test_login_returns_github_authorization_url():
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/api/auth/login")
    assert response.status_code == 200
    assert "github.com/login/oauth/authorize" in response.json()["login_url"]
    assert response.cookies.get("session")


def test_callback_rejects_missing_or_invalid_state():
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get(
            "/api/auth/callback",
            params={"code": "abc", "state": "bad"},
            follow_redirects=False,
        )
    assert response.status_code == 307
    assert response.headers["location"].endswith("/login?error=invalid_state")


def test_callback_completes_login_and_keeps_session(monkeypatch):
    async def fake_exchange_github_code(code: str) -> dict:
        assert code == "code-from-github"
        return {"access_token": "github-access-token"}

    async def fake_get_user(self) -> dict:
        return {
            "id": 9001,
            "login": "oauth-tester",
            "avatar_url": "https://example.com/avatar.png",
        }

    monkeypatch.setattr(auth_module, "exchange_github_code", fake_exchange_github_code)
    monkeypatch.setattr(GitHubClient, "get_user", fake_get_user)
    get_settings.cache_clear()

    with TestClient(app) as client:
        login_url = client.get("/api/auth/login").json()["login_url"]
        state = _state_from_login_url(login_url)
        callback = client.get(
            "/api/auth/callback",
            params={"code": "code-from-github", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 307
        assert callback.headers["location"].endswith("/repos")
        me = client.get("/api/auth/me")
        assert me.json()["user"]["username"] == "oauth-tester"
