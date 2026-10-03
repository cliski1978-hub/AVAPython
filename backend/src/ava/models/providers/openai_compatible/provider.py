"""OpenAI-compatible HTTP model provider adapter.

Implements ``ModelProviderPort`` for any server that exposes the
OpenAI-compatible chat-completions HTTP protocol (a local Ollama ``/v1``
endpoint, a company AI gateway, or an approved external provider). It speaks
the compatible protocol directly over generic async HTTP (httpx) — no vendor
SDK is required.

The adapter represents a *protocol*, not a deployment: the same class is usable
for local, corporate-gateway, and external OpenAI-compatible endpoints. It
never reads application settings or environment variables; configuration is
passed in through the constructor.

All protocol-specific JSON and HTTP behavior lives inside this adapter. AVA
contracts never expose httpx types, raw JSON dicts, or provider response
objects.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx

from ava.contracts.failures import FailureCode
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.models.bindings import RuntimeModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError

_DEFAULT_PROVIDER_NAME = "openai-compatible"
_DEFAULT_TIMEOUT_SECONDS = 30.0


# ============================================================
# BEGIN: Failure Classification
# ============================================================

#: Provider-side error identifiers that mean "the model you named does not
#: exist". Compared case-insensitively against the structured ``code`` field only.
_MODEL_NOT_FOUND_CODES = frozenset({"model_not_found", "model_not_exist", "unknown_model"})


def _structured_error(response: httpx.Response) -> tuple[str | None, str]:
    """Return ``(structured_code, safe_text)`` from a provider error body.

    Only the OpenAI-compatible error envelope is read: ``error.code`` for a
    machine-readable identifier and ``error.message`` (or a plain string
    ``error``) for the human-readable half. Anything else is ignored.

    This runs entirely server-side. Nothing derived from the body reaches the
    public failure payload: only the resulting AVA code does.
    """
    try:
        body = response.json()
    except ValueError:
        return None, ""
    if not isinstance(body, dict):
        return None, ""
    error = body.get("error")
    if isinstance(error, str):
        return None, error
    if not isinstance(error, dict):
        return None, ""
    code = error.get("code")
    message = error.get("message")
    return (code if isinstance(code, str) else None), (message if isinstance(message, str) else "")


def _is_model_not_found(status_code: int, response: httpx.Response) -> bool:
    """Whether a failure means the requested model does not exist.

    The protocol signal is a 404 on a chat-completions request, which is how
    OpenAI-compatible servers report an unknown model. A 404 is not conclusive on
    its own, because it also means "no such endpoint", so the structured
    ``error.code`` is preferred and the message is consulted only as a
    tie-breaker. This keeps the vendor-specific reading inside the adapter: no
    service outside this file ever sees a 404 or a provider body.
    """
    code, text = _structured_error(response)
    if code is not None and code.strip().lower() in _MODEL_NOT_FOUND_CODES:
        return True
    if status_code != 404:
        return False
    lowered = text.lower()
    return "model" in lowered and ("not found" in lowered or "not exist" in lowered or "does not exist" in lowered)


def _classify_status_failure(response: httpx.Response) -> ModelProviderError:
    """Map a non-success HTTP response to an AVA-owned classified error.

    Status code is the primary signal and the structured error code breaks ties.
    The returned message is AVA's own wording: it states the category and never
    quotes the provider, the endpoint, or the response body.
    """
    status = response.status_code
    if status in (401, 403):
        return ModelProviderError(
            "The OpenAI-compatible endpoint rejected the configured credentials",
            status_code=status,
            safe_code=FailureCode.PROVIDER_AUTHENTICATION_FAILED,
        )
    if _is_model_not_found(status, response):
        return ModelProviderError(
            "The OpenAI-compatible endpoint does not serve the requested model",
            status_code=status,
            safe_code=FailureCode.MODEL_UNAVAILABLE,
        )
    if status in (408, 504):
        return ModelProviderError(
            "The OpenAI-compatible endpoint timed out",
            status_code=status,
            safe_code=FailureCode.PROVIDER_TIMEOUT,
        )
    if status == 429:
        return ModelProviderError(
            "The OpenAI-compatible endpoint applied a rate limit",
            status_code=status,
            safe_code=FailureCode.PROVIDER_RATE_LIMITED,
        )
    return ModelProviderError(
        f"The OpenAI-compatible endpoint returned HTTP status {status}",
        status_code=status,
        safe_code=FailureCode.PROVIDER_REQUEST_FAILED,
    )


def _classify_transport_failure(exc: Exception) -> ModelProviderError:
    """Map a transport-level exception to an AVA-owned classified error.

    A refused connection, an unresolvable host, or a broken transport is a
    connectivity problem, which is deliberately *not* a model problem: reporting
    it as ``model_unavailable`` would send the user to edit a model that is
    configured correctly.
    """
    if isinstance(exc, httpx.InvalidURL):
        return ModelProviderError(
            "OpenAI-compatible base_url is invalid",
            safe_code=FailureCode.CONFIGURATION_INVALID,
        )
    if isinstance(exc, httpx.TimeoutException):
        return ModelProviderError(
            "The OpenAI-compatible request timed out",
            safe_code=FailureCode.PROVIDER_TIMEOUT,
        )
    return ModelProviderError(
        "Could not reach the OpenAI-compatible endpoint",
        safe_code=FailureCode.PROVIDER_CONNECTION_UNAVAILABLE,
    )


# ============================================================
# BEGIN: Base URL Configuration Validation
# ============================================================

_VALID_BASE_URL_SCHEMES = ("http", "https")


def _base_url_config_valid(base_url: str) -> bool:
    """Return whether ``base_url`` is structurally usable without I/O.

    Validates only what this adapter needs before handing the URL to the HTTP
    client: an ``http``/``https`` scheme, a hostname, and (when present) an
    in-range numeric port. An out-of-range port (e.g. ``:99999``) would
    otherwise surface as a raw ``ExceptionGroup`` from the async transport
    stack, and a non-numeric port would surface as ``httpx.InvalidURL`` — both
    sit outside the ``httpx`` exception hierarchy this adapter otherwise
    catches. Early validation turns malformed configuration into a
    deterministic configuration failure instead.
    """
    parts = urlsplit(base_url)
    if parts.scheme.lower() not in _VALID_BASE_URL_SCHEMES:
        return False
    if not parts.hostname:
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    return port is None or 1 <= port <= 65535


# ============================================================
# END: Base URL Configuration Validation
# ============================================================


# ============================================================
# BEGIN: Request / Response Translation
# ============================================================


def _to_chat_completion_payload(request: ModelRequest, model_name: str) -> dict[str, object]:
    """Translate an AVA ``ModelRequest`` into an OpenAI-compatible body.

    ``temperature`` (when supplied) and AVA ``max_output_tokens`` map to the
    protocol's ``temperature`` / ``max_tokens`` fields. Optional fields are
    omitted entirely when the AVA request does not supply them, so no
    unnecessary external field is sent.
    """
    payload: dict[str, object] = {
        "model": model_name,
        "messages": [{"role": message.role, "content": message.content} for message in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    return payload


def _from_chat_completion_response(payload: object, default_model_id: str) -> ModelResponse:
    """Translate an OpenAI-compatible response body into an AVA ``ModelResponse``.

    Malformed or incomplete provider responses fail deterministically with a
    ``ModelProviderError``: missing/empty ``choices``, a choice without a
    ``message``, or a message without string ``content`` are all rejected.
    """
    if not isinstance(payload, dict):
        raise ModelProviderError("OpenAI-compatible response must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise ModelProviderError("OpenAI-compatible response is missing 'choices'")
    if not choices:
        raise ModelProviderError("OpenAI-compatible response contained no choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ModelProviderError("OpenAI-compatible response choice must be a JSON object")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ModelProviderError("OpenAI-compatible response choice is missing a 'message'")
    if "content" not in message or message.get("content") is None:
        raise ModelProviderError("OpenAI-compatible response message is missing 'content'")
    content = message["content"]
    if not isinstance(content, str):
        raise ModelProviderError("OpenAI-compatible response message 'content' must be a string")
    model_id = payload.get("model")
    if not isinstance(model_id, str) or not model_id:
        model_id = default_model_id
    return ModelResponse(content=content, model_id=model_id)


# ============================================================
# END: Request / Response Translation
# ============================================================


# ============================================================
# BEGIN: OpenAI-Compatible Model Provider
# ============================================================


class OpenAICompatibleModelProvider(ModelProviderPort):
    """``ModelProviderPort`` adapter for OpenAI-compatible chat endpoints.

    Configuration is supplied explicitly at construction; the adapter never
    reads global application settings or environment variables. ``base_url``
    and ``model_name`` are required; ``api_key``, ``timeout``,
    ``capabilities``, ``context_limit``, ``display_name``, and an injected
    ``http_client`` are optional.

    Request/response translation is isolated in this adapter:
    ``ModelRequest`` → compatible request JSON → compatible response JSON →
    ``ModelResponse``. Generation targets ``POST {base_url}/chat/completions``
    and health probes ``GET {base_url}/models``.

    HTTP client ownership is explicit: a caller-injected ``http_client`` is
    the caller's to manage and is never closed here; a provider-created client
    is closed via ``aclose()`` (also entered and exited through ``async
    with``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        provider_name: str = _DEFAULT_PROVIDER_NAME,
        api_key: str | None = None,
        timeout: float | None = None,
        capabilities: ModelCapabilities | None = None,
        context_limit: int | None = None,
        display_name: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct the provider over an OpenAI-compatible endpoint.

        Args:
            base_url: Base URL of the OpenAI-compatible endpoint, e.g.
                ``"http://localhost:11434/v1"``.
            model_name: The model identifier to send in chat-completion
                requests, e.g. ``"llama3"``.
            provider_name: AVA provider name returned by ``name()`` and
                reported in ``ModelInfo``.
            api_key: Optional key sent as ``Authorization: Bearer <key>``.
                Never sent when absent. Never included in error messages.
            timeout: Optional per-request timeout in seconds for the default
                HTTP client.
            capabilities: Explicit ``ModelCapabilities``. When omitted, the
                adapter reports conservative ``chat=True`` (it implements the
                chat-completions protocol) with every other capability
                ``False``.
            context_limit: Optional configured context window for
                ``ModelInfo``.
            display_name: Optional human-readable model name for
                ``ModelInfo``.
            http_client: Optional pre-configured ``httpx.AsyncClient`` (e.g. a
                mocked transport in tests). When omitted, the provider
                creates and owns its own default async client, closed by
                ``aclose()``.

        Note:
            Construction is tolerant of blank ``base_url``/``model_name`` so
            that a misconfigured provider is discoverable at runtime:
            ``health()`` reports ``CONFIGURATION_INVALID`` and ``generate()``
            raises ``ModelProviderError``. Harmless outer whitespace on
            ``base_url`` is stripped at construction; structural URL validation
            happens before any I/O.
        """
        self._base_url = base_url.strip()
        self._model_name = model_name
        self._provider_name = provider_name
        self._api_key = api_key
        self._context_limit = context_limit
        self._display_name = display_name
        self._capabilities = capabilities if capabilities is not None else ModelCapabilities(chat=True)
        self._http_client = http_client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS
        )
        self._owns_http_client = http_client is None

    async def aclose(self) -> None:
        """Close the HTTP client only when the provider created it.

        A caller-injected ``http_client`` stays open and is never closed by
        the adapter. Safe to call more than once: after the first close the
        provider no longer owns (or re-closes) the client.
        """
        if self._owns_http_client:
            await self._http_client.aclose()
            self._owns_http_client = False

    async def __aenter__(self) -> OpenAICompatibleModelProvider:
        """Support ``async with`` to scope the client lifecycle explicitly."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the provider-owned HTTP client on ``async with`` exit."""
        await self.aclose()

    def name(self) -> str:
        """Return the configured provider name."""
        return self._provider_name

    async def health(self) -> ModelProviderHealth:
        """Probe the OpenAI-compatible endpoint's model-list resource.

        Uses ``GET {base_url}/models`` — a lightweight, broadly supported
        endpoint for OpenAI-compatible servers — and maps the result to
        ``ModelProviderHealth``:

        - 2xx → ``HEALTHY`` (available)
        - 401/403 → ``AUTHENTICATION_FAILED``
        - connection refusal → ``RUNTIME_UNAVAILABLE``
        - timeout/other transport failure → ``UNAVAILABLE``
        - invalid URL → ``CONFIGURATION_INVALID`` (configuration failure)
        - structurally invalid base URL (bad scheme/host/port) →
          ``CONFIGURATION_INVALID``, detected before I/O
        - any other non-2xx status → ``UNAVAILABLE``

        Never raises and never leaks HTTP-client exception types.
        """
        if not self._base_url.strip():
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.CONFIGURATION_INVALID,
                message="base_url is not configured",
            )
        if not _base_url_config_valid(self._base_url):
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.CONFIGURATION_INVALID,
                message="base_url is not a valid URL",
            )
        try:
            response = await self._http_client.get(self._models_url())
        except httpx.InvalidURL:
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.CONFIGURATION_INVALID,
                message="base_url is not a valid URL",
            )
        except httpx.ConnectError:
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.RUNTIME_UNAVAILABLE,
                message="Could not connect to the OpenAI-compatible endpoint",
            )
        except httpx.TimeoutException:
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.UNAVAILABLE,
                message="Timed out while reaching the OpenAI-compatible endpoint",
            )
        except httpx.RequestError:
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.UNAVAILABLE,
                message="Could not reach the OpenAI-compatible endpoint",
            )
        if response.status_code in (401, 403):
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.AUTHENTICATION_FAILED,
                message="The OpenAI-compatible endpoint rejected the configured credentials",
            )
        if response.status_code < 400:
            return ModelProviderHealth(
                available=True,
                status=ModelProviderHealthStatus.HEALTHY,
            )
        return ModelProviderHealth(
            available=False,
            status=ModelProviderHealthStatus.UNAVAILABLE,
            message=f"The OpenAI-compatible endpoint returned HTTP status {response.status_code}",
        )

    def get_model_info(self) -> ModelInfo:
        """Return configured AVA-side model metadata.

        Static/configured metadata only; no HTTP request is made.
        """
        return ModelInfo(
            provider_name=self._provider_name,
            model_id=self._model_name,
            display_name=self._display_name,
            context_limit=self._context_limit,
            capabilities=self.get_capabilities(),
        )

    def get_capabilities(self) -> ModelCapabilities:
        """Return the configured conservative capabilities."""
        return self._capabilities

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        """Send ``request`` to ``POST {base_url}/chat/completions``.

        The provider targets the explicit provider-native ``model_name`` when
        supplied (one provider may serve many deployments); otherwise it uses
        the bootstrap model name configured at construction. The provider never
        selects the model itself.

        Raises:
            ModelProviderError: For transport failures, invalid URLs,
                non-success HTTP statuses, and malformed/incomplete response
                bodies. Raw HTTP-client exception types never escape this
                method.
        """
        target_model = model_name if model_name is not None else self._model_name
        if not self._base_url.strip():
            raise ModelProviderError("base_url is not configured", safe_code=FailureCode.CONFIGURATION_INVALID)
        if not target_model.strip():
            raise ModelProviderError("model_name is not configured", safe_code=FailureCode.MODEL_UNAVAILABLE)
        if not _base_url_config_valid(self._base_url):
            raise ModelProviderError(
                "OpenAI-compatible base_url is invalid", safe_code=FailureCode.CONFIGURATION_INVALID
            )
        headers: dict[str, str] = {}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = await self._http_client.post(
                self._chat_completions_url(),
                headers=headers,
                json=_to_chat_completion_payload(request, target_model),
            )
        except (httpx.InvalidURL, httpx.TimeoutException, httpx.RequestError) as exc:
            raise _classify_transport_failure(exc) from exc
        if response.status_code not in (200, 201):
            raise _classify_status_failure(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                "The OpenAI-compatible response was not valid JSON",
                safe_code=FailureCode.PROVIDER_RESPONSE_INVALID,
            ) from exc
        try:
            return _from_chat_completion_response(payload, target_model)
        except ModelProviderError as exc:
            # A structurally unusable success body is a response problem, not a
            # transport one, and the adapter is the only layer that can tell.
            raise ModelProviderError(
                str(exc), status_code=exc.status_code, safe_code=FailureCode.PROVIDER_RESPONSE_INVALID
            ) from exc

    async def stream(self, request: ModelRequest, *, model_name: str | None = None) -> AsyncIterator[str]:
        """Yield real text deltas from an OpenAI-compatible SSE response."""
        target_model = model_name if model_name is not None else self._model_name
        if not self._base_url.strip() or not target_model.strip() or not _base_url_config_valid(self._base_url):
            raise ModelProviderError(
                "OpenAI-compatible streaming configuration is invalid",
                safe_code=FailureCode.CONFIGURATION_INVALID,
            )
        headers: dict[str, str] = {}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = _to_chat_completion_payload(request, target_model)
        payload["stream"] = True
        try:
            async with self._http_client.stream(
                "POST", self._chat_completions_url(), headers=headers, json=payload
            ) as response:
                if response.status_code not in (200, 201):
                    # A streamed response has no body until it is read, and
                    # classification reads the structured error. Skipping this
                    # turns a provider 404 into an httpx ResponseNotRead crash
                    # instead of an AVA-owned failure code.
                    await response.aread()
                    raise _classify_status_failure(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                        choices = event["choices"]
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                        raise ModelProviderError(
                            "The OpenAI-compatible stream payload was invalid",
                            safe_code=FailureCode.PROVIDER_RESPONSE_INVALID,
                        ) from exc
                    if content is None:
                        continue
                    if not isinstance(content, str):
                        raise ModelProviderError(
                            "OpenAI-compatible stream content must be text",
                            safe_code=FailureCode.PROVIDER_RESPONSE_INVALID,
                        )
                    if content:
                        yield content
        except ModelProviderError:
            raise
        except (httpx.InvalidURL, httpx.TimeoutException, httpx.RequestError) as exc:
            raise _classify_transport_failure(exc) from exc

    def _models_url(self) -> str:
        """Build the model-list URL from the configured base URL."""
        return f"{self._base_url.rstrip('/')}/models"

    def _chat_completions_url(self) -> str:
        """Build the chat-completions URL from the configured base URL."""
        return f"{self._base_url.rstrip('/')}/chat/completions"

    def create_runtime_model_binding(
        self, *, model_id: str, provider_id: str, provider_model_name: str
    ) -> RuntimeModelBinding:
        """Expose this provider's connection data with the selected identities.

        The provider owns protocol, endpoint, and credential; the caller owns
        the stable AVA ``model_id`` and ``provider_id`` and the selected
        provider-native ``provider_model_name``. The returned binding is
        internal-only.
        """
        return RuntimeModelBinding(
            model_id=model_id,
            provider_id=provider_id,
            provider_model_name=provider_model_name,
            protocol="openai-compatible",
            endpoint=self._base_url,
            api_key=self._api_key,
        )


# ============================================================
# END: OpenAI-Compatible Model Provider
# ============================================================
