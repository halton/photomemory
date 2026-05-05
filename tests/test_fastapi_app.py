"""Tests for the FastAPI application (api_fastapi.py)."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(scope="module")
def fastapi_app():
    """Import and return the FastAPI app, with env setup."""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)
    os.environ["PHOTOMEMORY_DB"] = db_path

    from backend.api_fastapi import app
    yield app

    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200(self, fastapi_app):
        """Health endpoint should return 200 with status ok."""
        from fastapi.testclient import TestClient
        client = TestClient(fastapi_app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data or "ok" in str(data).lower()


class TestAppStructure:
    """Tests for app configuration and routes."""

    def test_app_has_routes(self, fastapi_app):
        """App should have registered routes."""
        routes = [r.path for r in fastapi_app.routes]
        assert len(routes) > 0

    def test_app_has_health_route(self, fastapi_app):
        """App should have a health check route."""
        routes = [r.path for r in fastapi_app.routes]
        health_routes = [r for r in routes if "health" in r]
        assert len(health_routes) > 0

    def test_app_has_photos_routes(self, fastapi_app):
        """App should have photo-related routes."""
        routes = [r.path for r in fastapi_app.routes]
        photo_routes = [r for r in routes if "photo" in r]
        assert len(photo_routes) > 0


class TestErrorHandling:
    """Tests for error handling consistency."""

    def test_404_returns_json(self, fastapi_app):
        """Non-existent routes should return JSON error."""
        from fastapi.testclient import TestClient
        client = TestClient(fastapi_app)
        resp = client.get("/api/nonexistent-endpoint-xyz")
        assert resp.status_code in (404, 405)
        assert resp.headers.get("content-type", "").startswith("application/json")
