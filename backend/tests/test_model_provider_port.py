"""ModelProviderPort hardening tests.

Verify that the hardened model-provider boundary (Phase 3 Step 4) reports
capabilities through the AVA-owned ``ModelCapabilities`` contract rather than
``set[CapabilityName]``, and that every port input/output is an AVA-owned
contract with no vendor SDK type.
"""

import asyncio
import json

from ava.contracts.capabilities import CapabilityName
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelMessage,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.models.contracts import ModelProviderPort


class FakeModelProvider(ModelProviderPort):
    """Minimal test-only implementation of ModelProviderPort.

    Returns deterministic AVA-owned values only, so contract tests can run
    without a real provider or network access.
    """

    def __init__(
        self,
        *,
        model_id: str = "fake-model",
        capabilities: ModelCapabilities | None = None,
        health: ModelProviderHealth | None = None,
    ) -> None:
        self._model_id = model_id
        self._capabilities = capabilities if capabilities is not None else ModelCapabilities()
        self._health = health or ModelProviderHealth(
            available=True,
            status=ModelProviderHealthStatus.HEALTHY,
        )
        self.received_model_names: list[str | None] = []

    def name(self) -> str:
        return "fake"

    async def health(self) -> ModelProviderHealth:
        return self._health

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name=self.name(),
            model_id=self._model_id,
            display_name="Fake Model",
            context_limit=4096,
            capabilities=self.get_capabilities(),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        self.received_model_names.append(model_name)
        first_message = request.messages[0].content if request.messages else ""
        return ModelResponse(content=f"reply to {first_message}", model_id=model_name or self._model_id)


# ============================================================
# BEGIN: Port Capability Type Tests
# ============================================================


def test_get_capabilities_returns_model_capabilities() -> None:
    """A valid port implementation returns ModelCapabilities."""
    provider = FakeModelProvider()
    result = provider.get_capabilities()
    assert isinstance(result, ModelCapabilities)
    assert "tool_calling" in ModelCapabilities.model_fields
    json.dumps(result.model_dump())  # must not raise


def test_get_capabilities_no_longer_returns_capability_name_set() -> None:
    """The old set[CapabilityName] boundary must no longer define the port."""
    provider = FakeModelProvider()
    result = provider.get_capabilities()
    assert not isinstance(result, (set, frozenset))
    # CapabilityName remains an AVA application capability vocabulary.
    assert CapabilityName.HEALTH == "health"


# ============================================================
# END: Port Capability Type Tests
# ============================================================


# ============================================================
# BEGIN: ModelInfo Consistency Tests
# ============================================================


def test_get_model_info_returns_ava_owned_model_info() -> None:
    """ModelInfo carries identity, context limit, and capabilities."""
    provider = FakeModelProvider()
    info = provider.get_model_info()
    assert isinstance(info, ModelInfo)
    assert info.provider_name == "fake"
    assert info.model_id == "fake-model"
    assert info.context_limit == 4096


def test_get_model_info_capabilities_match_get_capabilities() -> None:
    """A provider's ModelInfo capabilities and get_capabilities agree."""
    capabilities = ModelCapabilities(chat=True, streaming=True, tool_calling=True)
    provider = FakeModelProvider(capabilities=capabilities)
    assert provider.get_model_info().capabilities == provider.get_capabilities()


# ============================================================
# END: ModelInfo Consistency Tests
# ============================================================


# ============================================================
# BEGIN: Generation Contract Tests
# ============================================================


def test_generate_uses_ava_owned_contracts() -> None:
    """generate() accepts ModelRequest and returns ModelResponse."""

    async def scenario() -> ModelResponse:
        provider = FakeModelProvider()
        request = ModelRequest(
            messages=[ModelMessage(role="user", content="Summarize the document")]
        )
        return await provider.generate(request)

    response = asyncio.run(scenario())
    assert isinstance(response, ModelResponse)
    assert response.content == "reply to Summarize the document"
    assert response.model_id == "fake-model"
    json.dumps(response.model_dump())  # must not raise


# ============================================================
# END: Generation Contract Tests
# ============================================================


# ============================================================
# BEGIN: Health Contract Tests
# ============================================================


def test_health_returns_ava_owned_health() -> None:
    """health() returns a provider-neutral ModelProviderHealth."""

    async def scenario() -> ModelProviderHealth:
        provider = FakeModelProvider()
        return await provider.health()

    health = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert health.available is True
    assert health.status == ModelProviderHealthStatus.HEALTHY
    json.dumps(health.model_dump())  # must not raise


# ============================================================
# END: Health Contract Tests
# ============================================================


# ============================================================
# BEGIN: Capability Reporting Tests
# ============================================================


def test_conservative_capability_reporting() -> None:
    """A provider using default ModelCapabilities reports all unsupported."""
    provider = FakeModelProvider()
    payload = provider.get_capabilities().model_dump()
    assert payload["chat"] is False
    assert payload["streaming"] is False
    assert payload["tool_calling"] is False
    assert payload["structured_output"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False


def test_explicit_capability_reporting() -> None:
    """A provider can declare capabilities without altering unrelated fields."""
    provider = FakeModelProvider(
        capabilities=ModelCapabilities(chat=True, streaming=True)
    )
    payload = provider.get_capabilities().model_dump()
    assert payload["chat"] is True
    assert payload["streaming"] is True
    assert payload["tool_calling"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False


# ============================================================
# END: Capability Reporting Tests
# ============================================================