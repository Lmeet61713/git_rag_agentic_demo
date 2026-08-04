from fastapi.testclient import TestClient

from backend.app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_repos_requires_login():
    with TestClient(app) as client:
        response = client.get("/api/repos")
        assert response.status_code == 401
