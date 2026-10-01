"""Provider-boundary failure classification tests.

The OpenAI-compatible adapter is the only layer that knows HTTP exists. These
tests pin the mapping from a protocol condition to an AVA-owned
:class:`FailureCode`, so that:

- a model the provider does not serve is ``model_unavailable`` and never a
  connectivity problem;
- an unreachable endpoint is ``provider_connection_unavailable`` and never a
  model problem;
- a timeout, a 429, and a rejected credential each keep their own code;
- a structurally unusable success body is ``provider_response_invalid``;
- the AVA-owned error carries no endpoint, no credential, and no response body.

No live provider, network access, or credentials are required.
"""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from ava.contracts.failures import FailureCode
from ava.contracts.models import ModelRequest
from ava.models.errors import ModelProviderError
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

_MODEL_NAME = "qwen2.5-coder:7b"
#: Values that must never appear in an AVA-owned provider error.
_SECRETS = ("sk-secret-value", "http://localhost:11434/v1", "/v1/chat/completions")


def _request() -> ModelRequest:
    return ModelRequest(messages=[{"role": "user", "content": "hello"}])


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://localhost:11434/v1",
    model_name: str = _MODEL_NAME,
    api_key: str | None = None,
) -> OpenAICompatibleModelProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleModelProvider(
        base_url=base_url,
        model_name=model_name,
        provider_name="openai-compatible",
        api_key=api_key,
        http_client=client,
    )


def _raise(handler: Callable[[httpx.Request], httpx.Response], **kwargs: object) -> ModelProviderError:
    """Run ``generate`` and return the classified provider error."""

    async def scenario() -> ModelProviderError:
        provider = _provider(handler, **kwargs)  # type: ignore[arg-type]
        with pytest.raises(ModelProviderError) as caught:
            await provider.generate(_request())
        return caught.value

    return asyncio.run(scenario())


def _http(status: int, body: object | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {"error": {"message": "redacted"}})

    return handler


# ============================================================
# BEGIN: Model Not Found
# ============================================================


def test_a_404_with_model_not_found_semantics_is_model_unavailable() -> None:
    # The live case: the operator configured a provider_model_name Ollama does
    # not have. It must not be reported as an unreachable provider.
    error = _raise(_http(404, {"error": "model 'Badmodelid' not found"}))
    assert error.safe_code == FailureCode.MODEL_UNAVAILABLE


def test_a_structured_model_not_found_code_wins_over_prose() -> None:
    error = _raise(
        _http(404, {"error": {"code": "model_not_found", "message": "unrecognized request argument"}})
    )
    assert error.safe_code == FailureCode.MODEL_UNAVAILABLE


def test_a_404_that_is_not_about_a_model_is_not_model_unavailable() -> None:
    # A wrong endpoint is a different problem from a wrong model; reporting it as
    # a model problem sends the user to edit a correct configuration.
    error = _raise(_http(404, {"error": {"message": "no such endpoint"}}))
    assert error.safe_code == FailureCode.PROVIDER_REQUEST_FAILED


def test_model_not_found_does_not_silently_substitute_another_model() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(404, json={"error": f"model '{_MODEL_NAME}' not found"})

    with pytest.raises(ModelProviderError):
        asyncio.run(_provider(handler).generate(_request()))
    # Exactly one attempt, for exactly the requested model.
    assert seen == [_MODEL_NAME]


# ============================================================
# BEGIN: Connectivity
# ============================================================


def test_a_refused_connection_is_provider_connection_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _raise(handler).safe_code == FailureCode.PROVIDER_CONNECTION_UNAVAILABLE


def test_a_dns_failure_is_provider_connection_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    assert _raise(handler).safe_code == FailureCode.PROVIDER_CONNECTION_UNAVAILABLE


def test_a_broken_transport_is_provider_connection_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("peer closed", request=request)

    assert _raise(handler).safe_code == FailureCode.PROVIDER_CONNECTION_UNAVAILABLE


# ============================================================
# BEGIN: Timeout, Authentication, Rate Limit, Server Error
# ============================================================


def test_a_timeout_is_provider_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    assert _raise(handler).safe_code == FailureCode.PROVIDER_TIMEOUT


def test_a_gateway_timeout_status_is_provider_timeout() -> None:
    assert _raise(_http(504)).safe_code == FailureCode.PROVIDER_TIMEOUT


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_are_provider_authentication_failed(status: int) -> None:
    assert _raise(_http(status)).safe_code == FailureCode.PROVIDER_AUTHENTICATION_FAILED


def test_rate_limiting_is_provider_rate_limited() -> None:
    assert _raise(_http(429)).safe_code == FailureCode.PROVIDER_RATE_LIMITED


@pytest.mark.parametrize("status", [400, 409, 500, 502, 503])
def test_other_statuses_are_provider_request_failed(status: int) -> None:
    assert _raise(_http(status)).safe_code == FailureCode.PROVIDER_REQUEST_FAILED


# ============================================================
# BEGIN: Invalid Response
# ============================================================


def test_malformed_json_is_provider_response_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not json")

    assert _raise(handler).safe_code == FailureCode.PROVIDER_RESPONSE_INVALID


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 5}}]},
    ],
)
def test_a_structurally_unusable_success_body_is_provider_response_invalid(body: object) -> None:
    assert _raise(_http(200, body)).safe_code == FailureCode.PROVIDER_RESPONSE_INVALID


# ============================================================
# BEGIN: Streaming
# ============================================================


async def _drain(provider: OpenAICompatibleModelProvider) -> None:
    async for _ in provider.stream(_request()):
        pass


def _stream_failure(handler: Callable[[httpx.Request], httpx.Response]) -> ModelProviderError:
    async def scenario() -> ModelProviderError:
        provider = _provider(handler)
        with pytest.raises(ModelProviderError) as caught:
            await _drain(provider)
        return caught.value

    return asyncio.run(scenario())


def test_streaming_classifies_a_404_as_model_unavailable() -> None:
    assert _stream_failure(_http(404, {"error": "model 'nope' not found"})).safe_code == (
        FailureCode.MODEL_UNAVAILABLE
    )


def test_streaming_classifies_a_429_as_provider_rate_limited() -> None:
    assert _stream_failure(_http(429)).safe_code == FailureCode.PROVIDER_RATE_LIMITED


def test_streaming_classifies_a_refused_connection_as_provider_connection_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _stream_failure(handler).safe_code == FailureCode.PROVIDER_CONNECTION_UNAVAILABLE


def test_a_malformed_stream_event_is_provider_response_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A well-formed delta first, so this also proves a mid-stream failure
        # still classifies rather than being absorbed.
        body = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: {not-json}\n\n'
        return httpx.Response(200, content=body.encode(), headers={"Content-Type": "text/event-stream"})

    assert _stream_failure(handler).safe_code == FailureCode.PROVIDER_RESPONSE_INVALID


# ============================================================
# BEGIN: Public Safety
# ============================================================


def test_no_classified_error_leaks_a_credential_endpoint_or_provider_body() -> None:
    """A provider error is safe to log and to carry across a service boundary."""
    secret_body = {
        "error": {
            "message": f"model '{_MODEL_NAME}' not found; key sk-secret-value rejected",
            "code": "model_not_found",
        }
    }
    error = _raise(_http(404, secret_body), api_key="sk-secret-value")

    rendered = f"{error} {error.safe_code}"
    for secret in _SECRETS:
        assert secret not in rendered
    assert error.safe_code not in _SECRETS


def test_the_status_code_is_kept_for_logs_but_is_not_part_of_the_public_code() -> None:
    error = _raise(_http(429))
    assert error.status_code == 429
    # The public classification is a taxonomy value, not an HTTP status.
    assert error.safe_code == FailureCode.PROVIDER_RATE_LIMITED
    assert "429" not in error.safe_code
