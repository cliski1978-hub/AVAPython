"""Capabilities endpoint tests.

Verify that /capabilities returns a versioned, JSON-compatible capability
snapshot that reflects the configured agent adapter truthfully (technical
health plus what the agent actually supports), reports only implemented
capabilities as true, and reflects the configurable application identity.
"""

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.contracts.capabilities import CapabilityName
from ava.contracts.version import CONTRACT_VERSION
from ava.core.application import Application, ApplicationConfig

# ============================================================
# BEGIN: Capabilities Endpoint Tests
# ============================================================


def make_client() -> TestClient:
    """Create a test client with a default application."""
    return TestClient(create_app())


def test_capabilities_returns_200() -> None:
    """GET /capabilities should return HTTP 200."""
    with make_client() as client:
        response = client.get("/capabilities")
    assert response.status_code == 200


def test_capabilities_return_contract_version() -> None:
    """GET /capabilities should report the current contract version."""
    with make_client() as client:
        response = client.get("/capabilities")
    assert response.json()["contract_version"] == CONTRACT_VERSION


def test_capabilities_report_application() -> None:
    """GET /capabilities should identify the AVA application."""
    with make_client() as client:
        response = client.get("/capabilities")
    assert response.json()["application"] == "AVA"


def test_capabilities_health_is_true() -> None:
    """Health is always reported as supported."""
    with make_client() as client:
        response = client.get("/capabilities")
    assert response.json()["capabilities"]["health"] is True


def test_capabilities_runs_and_cancellation_are_true() -> None:
    """The mock agent supports runs and cancellation, so they must be true."""
    with make_client() as client:
        response = client.get("/capabilities")
    capabilities = response.json()["capabilities"]
    assert capabilities["runs"] is True
    assert capabilities["cancellation"] is True


def test_capabilities_unsupported_features_are_false() -> None:
    """Not-yet-implemented capabilities should report false."""
    with make_client() as client:
        response = client.get("/capabilities")
    capabilities = response.json()["capabilities"]
    assert capabilities["streaming"] is False
    assert capabilities["tool_calling"] is False
    assert capabilities["structured_output"] is False
    assert capabilities["document_operations"] is False
    assert capabilities["approvals"] is False
    assert capabilities["local_model"] is False


def test_capabilities_report_every_known_capability_name() -> None:
    """Every CapabilityName in the contract should appear in the response."""
    with make_client() as client:
        response = client.get("/capabilities")
    reported = set(response.json()["capabilities"])
    assert reported == {capability.value for capability in CapabilityName}


def test_capabilities_use_configured_application_name() -> None:
    """The capability service should report the configured application root."""
    application = Application(
        config=ApplicationConfig(application_name="AVA Test")
    )
    with TestClient(create_app(application=application)) as client:
        capabilities = client.get("/capabilities").json()
        health = client.get("/health").json()
    assert capabilities["application"] == "AVA Test"
    assert health["application"] == "AVA Test"


# ============================================================
# END: Capabilities Endpoint Tests
# ============================================================