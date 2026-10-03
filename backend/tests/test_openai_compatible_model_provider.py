"""OpenAI-compatible HTTP model provider tests.

Verify the OpenAI-compatible adapter (Phase 3 Step 8):

- implements ``ModelProviderPort`` using AVA-owned contract types only;
- translates ``ModelRequest`` into the compatible request JSON and the
  compatible response JSON back into ``ModelResponse``;
- handles authentication, health, HTTP failures, timeouts, and malformed
  responses deterministically without leaking HTTP-client types.

All HTTP traffic runs through ``httpx.MockTransport`` — no live provider,
network access, or credentials are required.
"""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from ava.contracts.failures import FailureCode
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
from ava.models.errors import ModelProviderError
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider


def _ok_chat_completion() -> dict[str, object]:
    """A minimal well-formed OpenAI-compatible chat completion response."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "configured-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from the model!"},
            }
        ],
    }


def _configured_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://localhost:11434/v1",
    model_name: str = "configured-model",
    api_key: str | None = None,
    capabilities: ModelCapabilities | None = None,
    context_limit: int | None = None,
    display_name: str | None = None,
) -> OpenAICompatibleModelProvider:
    """Build a provider whose HTTP traffic is served by a mock transport."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleModelProvider(
        base_url=base_url,
        model_name=model_name,
        provider_name="openai-compatible",
        api_key=api_key,
        capabilities=capabilities,
        context_limit=context_limit,
        display_name=display_name,
        http_client=client,
    )


def _generate_with_response(payload: object) -> ModelProviderError:
    """Run generate() against a mocked 200 response body; return the error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        request = ModelRequest(messages=[ModelMessage(role="user", content="Hi")])
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(request)
        return exc_info.value

    return asyncio.run(scenario())


# ============================================================
# BEGIN: Port Implementation Tests
# ============================================================


def test_openai_compatible_provider_satisfies_model_provider_port() -> None:
    """The adapter is a ModelProviderPort using AVA-owned contract types."""

    async def scenario() -> tuple[object, object, object, object]:
        provider = _configured_provider(lambda req: httpx.Response(200, json={}))
        capabilities = provider.get_capabilities()
        info = provider.get_model_info()
        health = await provider.health()
        return provider, capabilities, info, health

    provider, capabilities, info, health = asyncio.run(scenario())
    assert isinstance(provider, ModelProviderPort)
    assert isinstance(capabilities, ModelCapabilities)
    assert isinstance(info, ModelInfo)
    assert isinstance(health, ModelProviderHealth)


def test_provider_does_not_expose_http_client_types() -> None:
    """Port methods return only AVA contracts; failures raise provider errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> tuple[ModelProviderHealth, ModelResponse]:
        provider = _configured_provider(handler)
        health = await provider.health()
        response = await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hi")])
        )
        return health, response

    health, response = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert isinstance(response, ModelResponse)
    json.dumps(health.model_dump())  # must not raise
    json.dumps(response.model_dump())  # must not raise


# ============================================================
# END: Port Implementation Tests
# ============================================================


# ============================================================
# BEGIN: Basic Generation Request Tests
# ============================================================


def test_generate_emits_chat_completions_request() -> None:
    """generate() POSTs model + messages to {base_url}/chat/completions."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        request = ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        await provider.generate(request)

    asyncio.run(scenario())
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "configured-model"
    assert body["messages"] == [{"role": "user", "content": "Hello"}]


def test_generate_translates_response_into_model_response() -> None:
    """A compatible response becomes an AVA ModelResponse with content/id."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> ModelResponse:
        provider = _configured_provider(handler)
        return await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )

    response = asyncio.run(scenario())
    assert isinstance(response, ModelResponse)
    assert response.content == "Hello from the model!"
    assert response.model_id == "configured-model"


def test_generate_targets_explicit_provider_native_model_name() -> None:
    """An explicit model_name selects the deployment; the provider never picks."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        payload = _ok_chat_completion()
        payload["model"] = "native-target"
        return httpx.Response(200, json=payload)

    async def scenario() -> ModelResponse:
        provider = _configured_provider(handler)
        return await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")]),
            model_name="native-target",
        )

    response = asyncio.run(scenario())
    assert captured["body"]["model"] == "native-target"
    assert response.model_id == "native-target"


def test_generate_normalizes_base_url_trailing_slash() -> None:
    """A trailing slash on base_url must not produce double slashes."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler, base_url="http://localhost:11434/v1/")
        await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )

    asyncio.run(scenario())
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"


# ============================================================
# END: Basic Generation Request Tests
# ============================================================


# ============================================================
# BEGIN: Message Translation Tests
# ============================================================


def test_generate_preserves_message_order_and_roles() -> None:
    """Root/CORE/Project layers and history retain order and role."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        request = ModelRequest(
            messages=[
                ModelMessage(role="system", content="AVA root."),
                ModelMessage(role="system", content="CORE: Line one\n\n  Indented line\n日本語 →"),
                ModelMessage(role="system", content="[PROJECT INSTRUCTIONS]\nProject marker β"),
                ModelMessage(role="user", content="First."),
                ModelMessage(role="assistant", content="Second."),
                ModelMessage(role="user", content="Third."),
            ]
        )
        await provider.generate(request)

    asyncio.run(scenario())
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["messages"] == [
        {"role": "system", "content": "AVA root."},
        {"role": "system", "content": "CORE: Line one\n\n  Indented line\n日本語 →"},
        {"role": "system", "content": "[PROJECT INSTRUCTIONS]\nProject marker β"},
        {"role": "user", "content": "First."},
        {"role": "assistant", "content": "Second."},
        {"role": "user", "content": "Third."},
    ]


# ============================================================
# END: Message Translation Tests
# ============================================================


# ============================================================
# BEGIN: Optional Temperature Tests
# ============================================================


def test_temperature_omitted_when_not_supplied() -> None:
    """No temperature field is sent when AVA supplies None."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        request = ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        await provider.generate(request)

    asyncio.run(scenario())
    body = captured["body"]
    assert isinstance(body, dict)
    assert "temperature" not in body


def test_temperature_included_when_supplied() -> None:
    """A supplied AVA temperature is translated to the protocol field."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        request = ModelRequest(
            messages=[ModelMessage(role="user", content="Hello")],
            temperature=0.25,
        )
        await provider.generate(request)

    asyncio.run(scenario())
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["temperature"] == 0.25


# ============================================================
# END: Optional Temperature Tests
# ============================================================


# ============================================================
# BEGIN: Optional Output Token Limit Tests
# ============================================================


def test_max_output_tokens_maps_to_protocol_field() -> None:
    """AVA max_output_tokens becomes the protocol's max_tokens field."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        request = ModelRequest(
            messages=[ModelMessage(role="user", content="Hello")],
            max_output_tokens=128,
        )
        await provider.generate(request)

    asyncio.run(scenario())
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 128
    assert "max_output_tokens" in ModelRequest.model_fields  # AVA field name unchanged


# ============================================================
# END: Optional Output Token Limit Tests
# ============================================================


# ============================================================
# BEGIN: Model Response Tests
# ============================================================


def test_generate_reports_model_id_from_response() -> None:
    """The compatible response's model identity becomes model_id."""
    response = _ok_chat_completion()
    response["model"] = "reported-model-1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    async def scenario() -> ModelResponse:
        provider = _configured_provider(handler)
        return await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )

    result = asyncio.run(scenario())
    assert result.model_id == "reported-model-1"


# ============================================================
# END: Model Response Tests
# ============================================================


# ============================================================
# BEGIN: Authentication Header Tests
# ============================================================


def test_api_key_sends_bearer_authorization_header() -> None:
    """An configured API key is sent as Authorization: Bearer <key>."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler, api_key="test-secret-key")
        await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )

    asyncio.run(scenario())
    assert captured["authorization"] == "Bearer test-secret-key"


def test_no_api_key_omits_authorization_header() -> None:
    """Without a key, no Authorization header is sent."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["has_authorization"] = "Authorization" in request.headers
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        provider = _configured_provider(handler)
        await provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )

    asyncio.run(scenario())
    assert captured["has_authorization"] is False


def test_provider_error_messages_never_include_api_key() -> None:
    """Errors from an authenticated generate() leak no credentials."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(401, json={})

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler, api_key="super-secret-key")
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert "super-secret-key" not in str(error)
    assert captured["authorization"] == "Bearer super-secret-key"


# ============================================================
# END: Authentication Header Tests
# ============================================================


# ============================================================
# BEGIN: Health Success Tests
# ============================================================


def test_health_reports_healthy_when_models_endpoint_succeeds() -> None:
    """A 2xx GET {base_url}/models maps to HEALTHY and available=True."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "configured-model"}]})

    async def scenario() -> ModelProviderHealth:
        provider = _configured_provider(handler)
        return await provider.health()

    health = asyncio.run(scenario())
    assert captured["url"] == "http://localhost:11434/v1/models"
    assert health.available is True
    assert health.status == ModelProviderHealthStatus.HEALTHY


def test_health_other_http_errors_map_to_unavailable() -> None:
    """A non-auth non-2xx health probe maps to UNAVAILABLE."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(503, json={})

    async def scenario() -> ModelProviderHealth:
        provider = _configured_provider(handler)
        return await provider.health()

    health = asyncio.run(scenario())
    assert captured["url"] == "http://localhost:11434/v1/models"
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.UNAVAILABLE


# ============================================================
# END: Health Success Tests
# ============================================================


# ============================================================
# BEGIN: Health Connection Failure Tests
# ============================================================


def test_health_connection_failure_returns_runtime_unavailable() -> None:
    """A connection refusal maps to RUNTIME_UNAVAILABLE, never raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async def scenario() -> ModelProviderHealth:
        provider = _configured_provider(handler)
        return await provider.health()

    health = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.RUNTIME_UNAVAILABLE


def test_health_timeout_returns_unavailable_without_leaking() -> None:
    """A transport timeout maps to UNAVAILABLE; no client exception leaks."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    async def scenario() -> ModelProviderHealth:
        provider = _configured_provider(handler)
        return await provider.health()

    health = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.UNAVAILABLE


# ============================================================
# END: Health Connection Failure Tests
# ============================================================


# ============================================================
# BEGIN: Authentication Failure Tests
# ============================================================


@pytest.mark.parametrize("status_code", [401, 403])
def test_health_authentication_failure_returns_authentication_failed(status_code: int) -> None:
    """401/403 health probes map to AUTHENTICATION_FAILED."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={})

    async def scenario() -> ModelProviderHealth:
        provider = _configured_provider(handler)
        return await provider.health()

    health = asyncio.run(scenario())
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.AUTHENTICATION_FAILED


def test_health_blank_base_url_reports_configuration_invalid() -> None:
    """A blank base_url maps to CONFIGURATION_INVALID without I/O."""

    async def scenario() -> ModelProviderHealth:
        provider = OpenAICompatibleModelProvider(base_url="   ", model_name="configured-model")
        return await provider.health()

    health = asyncio.run(scenario())
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.CONFIGURATION_INVALID


# ============================================================
# END: Authentication Failure Tests
# ============================================================


# ============================================================
# BEGIN: Generation HTTP Error Tests
# ============================================================


def test_generate_non_success_status_raises_provider_error() -> None:
    """A 500 response raises ModelProviderError carrying the status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)
    assert error.status_code == 500


def test_generate_authentication_status_raises_provider_error() -> None:
    """A 401 during generation also raises a provider-layer error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert error.status_code == 401


# ============================================================
# END: Generation HTTP Error Tests
# ============================================================


# ============================================================
# BEGIN: Generation Timeout / Connection Error Tests
# ============================================================


def test_generate_timeout_raises_provider_error_not_http_client() -> None:
    """A timeout during generation is wrapped in ModelProviderError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


def test_generate_connection_error_raises_provider_error() -> None:
    """A connection refusal during generation is wrapped, not leaked."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


def test_generate_blank_model_name_raises_provider_error() -> None:
    """A blank model_name fails deterministically at the AVA boundary."""

    async def scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="   ",
        )
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


# ============================================================
# END: Generation Timeout / Connection Error Tests
# ============================================================


# ============================================================
# BEGIN: Malformed Response Tests
# ============================================================


def test_generate_missing_choices_fails() -> None:
    """A response without choices fails deterministically."""
    error = _generate_with_response({"model": "configured-model"})
    assert isinstance(error, ModelProviderError)


def test_generate_empty_choices_fails() -> None:
    """A response with empty choices fails deterministically."""
    error = _generate_with_response({"model": "configured-model", "choices": []})
    assert isinstance(error, ModelProviderError)


def test_generate_missing_message_fails() -> None:
    """A choice without a message fails deterministically."""
    response = {"model": "configured-model", "choices": [{"index": 0}]}
    error = _generate_with_response(response)
    assert isinstance(error, ModelProviderError)


def test_generate_missing_content_fails() -> None:
    """A message without content fails deterministically."""
    response = {
        "model": "configured-model",
        "choices": [{"index": 0, "message": {"role": "assistant"}}],
    }
    error = _generate_with_response(response)
    assert isinstance(error, ModelProviderError)


def test_generate_null_content_fails() -> None:
    """A message with null content fails deterministically."""
    response = {
        "model": "configured-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": None}}],
    }
    error = _generate_with_response(response)
    assert isinstance(error, ModelProviderError)


def test_generate_invalid_json_fails() -> None:
    """Invalid JSON body fails deterministically."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not valid json")

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(handler)
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)


def test_generate_non_object_payload_fails() -> None:
    """A non-object JSON body (e.g. a JSON array) fails deterministically."""
    error = _generate_with_response(["not", "an", "object"])
    assert isinstance(error, ModelProviderError)


# ============================================================
# END: Malformed Response Tests
# ============================================================


# ============================================================
# BEGIN: Model Info Tests
# ============================================================


def test_get_model_info_returns_configured_metadata() -> None:
    """get_model_info() reflects the configured provider/model metadata."""
    capabilities = ModelCapabilities(chat=True, streaming=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> ModelInfo:
        provider = _configured_provider(
            handler,
            context_limit=8192,
            display_name="Local Llama",
            capabilities=capabilities,
        )
        return provider.get_model_info()

    info = asyncio.run(scenario())
    assert info.provider_name == "openai-compatible"
    assert info.model_id == "configured-model"
    assert info.display_name == "Local Llama"
    assert info.context_limit == 8192
    assert info.capabilities == capabilities


def test_get_model_info_matches_get_capabilities() -> None:
    """ModelInfo.capabilities and get_capabilities() agree by contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> tuple[ModelInfo, ModelCapabilities]:
        provider = _configured_provider(handler)
        return provider.get_model_info(), provider.get_capabilities()

    info, capabilities = asyncio.run(scenario())
    assert info.capabilities == capabilities


# ============================================================
# END: Model Info Tests
# ============================================================


# ============================================================
# BEGIN: Capability Tests
# ============================================================


def test_default_capabilities_report_chat_only() -> None:
    """Defaults are conservative: chat=True, every other capability False.

    The adapter specifically implements the compatible chat-completions
    protocol, so ``chat`` is enabled by default. No unrelated capability is
    inferred merely because the endpoint might support it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> ModelCapabilities:
        provider = _configured_provider(handler)
        return provider.get_capabilities()

    payload = asyncio.run(scenario()).model_dump()
    assert payload["chat"] is True
    assert payload["streaming"] is False
    assert payload["tool_calling"] is False
    assert payload["structured_output"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False


def test_explicit_capabilities_remain_independent() -> None:
    """Explicitly supplied capabilities are used unchanged."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> ModelCapabilities:
        provider = _configured_provider(
            handler,
            capabilities=ModelCapabilities(chat=True, streaming=True),
        )
        return provider.get_capabilities()

    payload = asyncio.run(scenario()).model_dump()
    assert payload["chat"] is True
    assert payload["streaming"] is True
    assert payload["tool_calling"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False


# ============================================================
# END: Capability Tests
# ============================================================


# ============================================================
# BEGIN: HTTP Client Lifecycle Tests
# ============================================================


def test_provider_owned_client_is_closed_by_aclose() -> None:
    """aclose() closes an internally created HTTP client."""

    async def scenario() -> bool:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="configured-model",
        )
        client = provider._http_client
        assert client.is_closed is False
        await provider.aclose()
        return client.is_closed

    assert asyncio.run(scenario()) is True


def test_aclose_does_not_close_injected_client() -> None:
    """aclose() never closes a caller-injected client; the caller still owns it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="configured-model",
            http_client=client,
        )
        await provider.aclose()
        assert client.is_closed is False
        response = await client.get("http://localhost:11434/v1/models")
        assert response.status_code == 200
        await client.aclose()
        assert client.is_closed is True

    asyncio.run(scenario())


def test_aclose_is_safe_to_call_repeatedly() -> None:
    """aclose() is idempotent: repeated calls never fail."""

    async def scenario() -> bool:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="configured-model",
        )
        client = provider._http_client
        await provider.aclose()
        await provider.aclose()
        return client.is_closed

    assert asyncio.run(scenario()) is True


def test_async_context_manager_closes_provider_owned_client() -> None:
    """async with closes a provider-owned client on block exit."""

    async def scenario() -> bool:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="configured-model",
        )
        client = provider._http_client
        assert client.is_closed is False
        async with provider:
            assert client.is_closed is False
        return client.is_closed

    assert asyncio.run(scenario()) is True


def test_async_context_manager_does_not_close_injected_client() -> None:
    """async with leaves a caller-injected client open for the caller."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_chat_completion())

    async def scenario() -> bool:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:11434/v1",
            model_name="configured-model",
            http_client=client,
        )
        async with provider:
            assert client.is_closed is False
        return client.is_closed

    assert asyncio.run(scenario()) is False


# ============================================================
# END: HTTP Client Lifecycle Tests
# ============================================================


# ============================================================
# BEGIN: Invalid URL Error Boundary Tests
# ============================================================


def test_generate_invalid_base_url_raises_provider_error() -> None:
    """A malformed URL triggering httpx.InvalidURL is wrapped, not leaked."""

    async def scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:abc/v1",
            model_name="configured-model",
        )
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.InvalidURL)
    assert not isinstance(error, httpx.RequestError)


def test_generate_invalid_base_url_error_message_has_no_url() -> None:
    """The wrapped error never exposes the malformed URL text."""

    async def scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:abc/v1",
            model_name="configured-model",
        )
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert "localhost" not in str(error)


def test_health_invalid_base_url_returns_configuration_invalid() -> None:
    """A malformed URL maps to CONFIGURATION_INVALID, never raising."""

    async def scenario() -> ModelProviderHealth:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:abc/v1",
            model_name="configured-model",
        )
        return await provider.health()

    health = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.CONFIGURATION_INVALID


def test_generate_whitespace_only_base_url_fails_deterministically() -> None:
    """A whitespace-only base_url never reaches the HTTP client."""

    async def scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(base_url="   ", model_name="configured-model")
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


# ============================================================
# END: Invalid URL Error Boundary Tests
# ============================================================


# ============================================================
# BEGIN: Transport Configuration Boundary Tests
# ============================================================


def test_generate_out_of_range_port_raises_provider_error() -> None:
    """An out-of-range port is a config failure, not a raw transport leak."""

    async def scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:99999/v1",
            model_name="configured-model",
        )
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    error = asyncio.run(scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


def test_generate_out_of_range_port_is_rejected_before_io() -> None:
    """Malformed configuration never reaches the transport stack."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport must not receive a malformed URL")

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:99999/v1",
            model_name="configured-model",
            http_client=client,
        )
        with pytest.raises(ModelProviderError):
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )

    asyncio.run(scenario())


def test_health_out_of_range_port_returns_configuration_invalid() -> None:
    """An out-of-range port maps to CONFIGURATION_INVALID, never raising."""

    async def scenario() -> ModelProviderHealth:
        provider = OpenAICompatibleModelProvider(
            base_url="http://localhost:99999/v1",
            model_name="configured-model",
        )
        return await provider.health()

    health = asyncio.run(scenario())
    assert isinstance(health, ModelProviderHealth)
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.CONFIGURATION_INVALID


def test_base_url_outer_whitespace_is_normalized() -> None:
    """Harmless outer whitespace is stripped; paths stay clean with no '//'."""
    urls: dict[str, str] = {}

    def generate_handler(request: httpx.Request) -> httpx.Response:
        urls["generate"] = str(request.url)
        return httpx.Response(200, json=_ok_chat_completion())

    def health_handler(request: httpx.Request) -> httpx.Response:
        urls["health"] = str(request.url)
        return httpx.Response(200, json={"data": []})

    async def scenario() -> None:
        generate_provider = _configured_provider(
            generate_handler,
            base_url="  http://localhost:11434/v1/  ",
        )
        health_provider = _configured_provider(
            health_handler,
            base_url="  http://localhost:11434/v1/  ",
        )
        await generate_provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
        )
        await health_provider.health()

    asyncio.run(scenario())
    assert urls["generate"] == "http://localhost:11434/v1/chat/completions"
    assert urls["health"] == "http://localhost:11434/v1/models"
    assert " " not in urls["generate"]
    assert " " not in urls["health"]
    assert "//" not in urls["generate"].split("://", 1)[1]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:0/v1",
        "localhost:11434/v1",
        "http:///v1",
        "http://localhost:abc/v1",
        "ftp://localhost/v1",
    ],
)
def test_malformed_base_url_is_contained_for_generate_and_health(base_url: str) -> None:
    """Malformed base URLs fail as configuration for both operations."""

    async def health_scenario() -> ModelProviderHealth:
        provider = OpenAICompatibleModelProvider(base_url=base_url, model_name="configured-model")
        return await provider.health()

    async def generate_scenario() -> ModelProviderError:
        provider = OpenAICompatibleModelProvider(base_url=base_url, model_name="configured-model")
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.generate(
                ModelRequest(messages=[ModelMessage(role="user", content="Hello")])
            )
        return exc_info.value

    health = asyncio.run(health_scenario())
    assert health.available is False
    assert health.status == ModelProviderHealthStatus.CONFIGURATION_INVALID

    error = asyncio.run(generate_scenario())
    assert isinstance(error, ModelProviderError)
    assert not isinstance(error, httpx.RequestError)


# ============================================================
# END: Transport Configuration Boundary Tests
# ============================================================

# ============================================================
# BEGIN: Charter B - Streaming Failure Classification Tests
# ============================================================


def test_a_streamed_error_response_is_classified_rather_than_crashing() -> None:
    """A streamed non-200 must produce an AVA failure code, not an httpx error.

    A streamed response carries no body until it is read, so classification
    that inspects the structured provider error has to read it first. Skipping
    that read turns a plain "model not found" into an opaque
    ``ResponseNotRead``, which is how a misconfigured streaming model used to
    surface as a generic ``agent_failed`` with no actionable code.
    """

    body = b'{"error":{"code":"model_not_found","message":"no such model"}}'

    def handler(request: httpx.Request) -> httpx.Response:
        # A stream-backed body is unread, exactly like a real provider
        # response; an eagerly-built ``json=`` body would hide the defect.
        return httpx.Response(404, stream=httpx.ByteStream(body))

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(
            handler, capabilities=ModelCapabilities(chat=True, streaming=True)
        )
        request = ModelRequest(messages=[ModelMessage(role="user", content="Hi")])
        with pytest.raises(ModelProviderError) as exc_info:
            async for _ in provider.stream(request):
                pass
        return exc_info.value

    error = asyncio.run(scenario())
    assert error.safe_code == FailureCode.MODEL_UNAVAILABLE
    assert "model_not_found" not in str(error)


def test_a_streamed_auth_failure_keeps_its_specific_code() -> None:
    """Fine-grained error handling must hold on the streaming path too."""

    body = b'{"error":{"message":"bad key"}}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, stream=httpx.ByteStream(body))

    async def scenario() -> ModelProviderError:
        provider = _configured_provider(
            handler, api_key="secret", capabilities=ModelCapabilities(chat=True, streaming=True)
        )
        request = ModelRequest(messages=[ModelMessage(role="user", content="Hi")])
        with pytest.raises(ModelProviderError) as exc_info:
            async for _ in provider.stream(request):
                pass
        return exc_info.value

    error = asyncio.run(scenario())
    assert error.safe_code == FailureCode.PROVIDER_AUTHENTICATION_FAILED
    assert "secret" not in str(error)


# ============================================================
# END: Charter B - Streaming Failure Classification Tests
# ============================================================
