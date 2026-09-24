"""Model provider discovery endpoint tests.

Verify (Phase 3 Step 10) that GET /model-providers returns the discovered
provider snapshot through the composed local provider, and that an offline
Ollama runtime is surfaced as an unavailable (never raising) report. The local
provider is exercised for real through ``httpx.MockTransport`` — no live
localhost connection and no real network requests are made.
"""

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.version import CONTRACT_VERSION
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider
from ava.models.registry import ModelProviderRegistry

#: All environment variables the settings layer reads. Tests clear them so
#: they assert on explicit values rather than ambient environment state.
_AVA_VARS = (
    "AVA_APPLICATION",
    "AVA_ENVIRONMENT",
    "AVA_AGENT_PROVIDER",
    "AVA_MODEL_PROVIDER",
    "AVA_MODEL_NAME",
    "AVA_LOCAL_MODEL_BASE_URL",
    "AVA_HOST",
    "AVA_PORT",
    "AVA_DEBUG",
    "AVA_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove AVA_* variables and reset the cached settings before every test."""
    for name in _AVA_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("ava.configuration.settings._settings", None)


def _compose_app_with_mock_local_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> TestClient:
    """Compose the real application but reroute the local provider's transport.

    ``create_model_provider_registry`` builds the real
    ``OpenAICompatibleModelProvider`` (exactly as production composition does);
    the provider's HTTP client is then swapped for one backed by
    ``httpx.MockTransport``. Production wiring, lifespan, and the discovery
    service all run unchanged, while no real endpoint is contacted.
    """
    from ava.infrastructure.composition import create_model_provider_registry as real_composition

    def compose_registry(settings: Settings) -> ModelProviderRegistry:
        registry = real_composition(settings)
        provider = registry.get("local")
        assert isinstance(provider, OpenAICompatibleModelProvider), "expected the composed local provider"
        provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return registry

    monkeypatch.setattr("ava.api.app.create_model_provider_registry", compose_registry)
    return TestClient(create_app())


# ============================================================
# BEGIN: Model Provider Discovery Endpoint Tests
# ============================================================


def test_model_providers_reports_healthy_composed_local_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /model-providers reports the composed local provider when reachable."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"object": "list", "data": []})

    with _compose_app_with_mock_local_transport(monkeypatch, handle) as client:
        response = client.get("/model-providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["default_provider_id"] == "local"
    assert [item["provider_id"] for item in payload["providers"]] == ["local"]
    provider = payload["providers"][0]
    assert provider["is_default"] is True
    assert provider["model_info"]["model_id"] == "local-model"
    assert provider["health"]["available"] is True
    assert provider["health"]["status"] == "healthy"


def test_model_providers_survives_offline_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable Ollama runtime is reported, never raised or leaked."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _compose_app_with_mock_local_transport(monkeypatch, handle) as client:
        response = client.get("/model-providers")

    assert response.status_code == 200
    payload = response.json()
    assert [item["provider_id"] for item in payload["providers"]] == ["local"]
    provider = payload["providers"][0]
    assert provider["model_info"]["model_id"] == "local-model"
    assert provider["health"]["available"] is False
    assert provider["health"]["status"] == "runtime_unavailable"


def test_model_providers_never_contacts_a_real_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint works entirely through the mock transport — no real I/O."""
    called: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        return httpx.Response(200, json={"object": "list", "data": []})

    with _compose_app_with_mock_local_transport(monkeypatch, handle) as client:
        response = client.get("/model-providers")

    assert response.status_code == 200
    assert called == ["/v1/models"]


# ============================================================
# END: Model Provider Discovery Endpoint Tests
# ============================================================