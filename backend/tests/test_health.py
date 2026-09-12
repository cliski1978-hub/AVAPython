"""Health endpoint tests."""

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.contracts.version import CONTRACT_VERSION


def make_client() -> TestClient:
    """Create a test client with a default application."""
    return TestClient(create_app())


# ============================================================
# BEGIN: Health Endpoint Tests
# ============================================================


def test_health_returns_200() -> None:
    """GET /health should return HTTP 200."""
    with make_client() as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ava_application() -> None:
    """GET /health should identify the AVA application."""
    with make_client() as client:
        response = client.get("/health")
    assert response.json()["application"] == "AVA"


def test_health_returns_healthy_status() -> None:
    """GET /health should return a healthy status."""
    with make_client() as client:
        response = client.get("/health")
    assert response.json()["status"] == "healthy"


def test_health_returns_contract_version() -> None:
    """GET /health should return the current contract version on the wire."""
    with make_client() as client:
        response = client.get("/health")
    assert response.json()["contract_version"] == CONTRACT_VERSION


# ============================================================
# END: Health Endpoint Tests
# ============================================================
