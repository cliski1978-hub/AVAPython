"""Durable conversation failure classification, end to end.

A failure crosses four boundaries — provider adapter, runtime, agent, run
service — and must arrive at the public ``run_failed`` payload still naming what
actually went wrong. These tests pin the durable ``error_code``, the
``recoverable`` flag, and the safe public message for each layer, and assert
that no raw provider wording, status, endpoint, or credential ever crosses into
the public record.

Every case runs through the real HTTP API with a mocked provider transport.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ava.configuration.settings import Settings
from ava.contracts.failures import PUBLIC_FAILURE_MESSAGES, FailureCode

app_module = pytest.importorskip("ava.api.app")

SECRET = "fine-grained-secret-value"
ENDPOINT = "https://gateway.test/v1"


def _settings(tmp_path) -> Settings:
    return Settings(
        agent_provider="native",
        agent_runtime="native",
        model_provider="local",
        model_name="vendor/model",
        model_id="configured-model",
        local_model_base_url=ENDPOINT,
        persistence_provider="memory",
        persistence_database_url=str(tmp_path / "failures.sqlite3"),
        attachment_storage="memory",
    )


def _configure(client: TestClient) -> None:
    assert client.post(
        "/settings/providers",
        json={
            "provider_connection_id": "gateway",
            "provider_id": "local",
            "display_name": "Gateway",
            "endpoint": ENDPOINT,
            "enabled": True,
        },
    ).status_code == 201
    assert client.post(
        "/settings/models",
        json={
            "model_id": "configured-model",
            "provider_connection_id": "gateway",
            "provider_model_name": "vendor/model",
            "display_name": "Configured model",
            "hosting_mode": "company_hosted",
            "capabilities": {"chat": True},
            "enabled": True,
        },
    ).status_code == 201
    assert client.post(
        "/settings/runtimes",
        json={
            "runtime_configuration_id": "configured-runtime",
            "runtime_type": "native",
            "display_name": "Runtime",
            "enabled": True,
        },
    ).status_code == 201
    assert client.put(
        "/settings/defaults",
        json={
            "default_provider_connection_id": "gateway",
            "default_model_id": "configured-model",
            "default_runtime_configuration_id": "configured-runtime",
        },
    ).status_code == 200


def _app_with_provider(tmp_path, monkeypatch, responder):
    """An app whose only HTTP traffic is served by ``responder``."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    factories: list[object] = []

    def make_factory(settings, registry):
        from ava.infrastructure.model_provider_factory import ConfiguredModelProviderFactory

        factory = ConfiguredModelProviderFactory(
            installed_provider_ids=frozenset({"local"}),
            default_endpoint=settings.local_model_base_url,
            http_client=http,
        )
        factories.append(factory)
        return factory

    monkeypatch.setattr(app_module, "create_configured_model_provider_factory", make_factory)
    monkeypatch.setenv("AVA_PHASE516_KEY", SECRET)
    return app_module.create_app(settings=_settings(tmp_path))


def _failed_payload(client: TestClient, prompt: str = "hello", execution: dict | None = None) -> dict:
    body = {"prompt": prompt}
    if execution is not None:
        body["execution"] = execution
    accepted = client.post("/runs", json=body)
    assert accepted.status_code == 202, accepted.text
    events = client.get(f"/runs/{accepted.json()['run_id']}/events").json()
    failures = [e for e in events if e["event_type"] == "run_failed"]
    assert len(failures) == 1, events
    return failures[0]["payload"]


# ============================================================
# BEGIN: Provider Conditions Reach the Durable Record
# ============================================================


def test_a_model_the_provider_does_not_serve_is_durably_model_unavailable(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": f"model 'vendor/model' not found; key {SECRET}"})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.MODEL_UNAVAILABLE
    assert payload["message"] == PUBLIC_FAILURE_MESSAGES[FailureCode.MODEL_UNAVAILABLE]
    assert payload["recoverable"] is True
    # The provider's own wording and the credential never reach the public body.
    assert "not found" not in payload["message"]
    assert SECRET not in json.dumps(payload)


def test_an_unreachable_endpoint_is_durably_provider_connection_unavailable(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused to {ENDPOINT}", request=request)

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_CONNECTION_UNAVAILABLE
    assert payload["recoverable"] is True
    assert ENDPOINT not in json.dumps(payload)


def test_a_slow_provider_is_durably_provider_timeout(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_TIMEOUT
    assert payload["recoverable"] is True


def test_rejected_credentials_are_durably_provider_authentication_failed(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"invalid api key {SECRET}"}})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_AUTHENTICATION_FAILED
    assert payload["recoverable"] is False
    assert SECRET not in json.dumps(payload)


def test_a_rate_limited_provider_is_durably_provider_rate_limited(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_RATE_LIMITED
    assert payload["recoverable"] is True


def test_a_server_error_is_durably_provider_request_failed(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down", headers={"Content-Type": "text/plain"})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_REQUEST_FAILED
    assert "upstream down" not in json.dumps(payload)


def test_an_unusable_success_body_is_durably_provider_response_invalid(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {}}]})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.PROVIDER_RESPONSE_INVALID


def test_an_unexpected_exception_still_takes_the_generic_fallback(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError(f"unexpected transport fault {SECRET}", request=request)

    # A broken transport is classified; force a genuinely unknown failure by
    # making the provider itself misbehave in a way nothing recognizes.
    from ava.models.errors import ModelProviderError

    def unknown(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the provider must not be reached")

    with TestClient(_app_with_provider(tmp_path, monkeypatch, unknown)) as client:
        _configure(client)
        app_runtime = client.app.state.model_provider_registry.get("local")
        original_generate = app_runtime.generate

        async def explode(*args, **kwargs):
            raise ValueError(f"unexpected internal fault {SECRET}")

        app_runtime.generate = explode  # type: ignore[method-assign]
        try:
            payload = _failed_payload(client)
        finally:
            app_runtime.generate = original_generate  # type: ignore[method-assign]

    assert payload["error_code"] == FailureCode.AGENT_FAILED
    assert payload["message"] == PUBLIC_FAILURE_MESSAGES[FailureCode.AGENT_FAILED]
    assert payload["recoverable"] is False
    assert SECRET not in json.dumps(payload)
    assert ModelProviderError is not None


# ============================================================
# BEGIN: Configuration Conditions
# ============================================================


def test_a_disabled_model_fails_before_the_provider_and_is_specific(tmp_path, monkeypatch):
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        model = client.get("/settings/models").json()["models"][0]
        # The route replaces the record, so the full body must be resent.
        disabled = client.put(
            f"/settings/models/{model['model_id']}",
            json={
                "provider_connection_id": model["provider_connection_id"],
                "provider_model_name": model["provider_model_name"],
                "display_name": model["display_name"],
                "hosting_mode": model["hosting_mode"],
                "capabilities": model["capabilities"],
                "enabled": False,
            },
        )
        assert disabled.status_code == 200, disabled.text
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.CONFIGURATION_INVALID
    assert payload["recoverable"] is False
    # The refusal happens in AVA, before any provider work.
    assert calls == []


def test_a_disabled_provider_connection_fails_before_the_provider(tmp_path, monkeypatch):
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        disabled = client.put(
            "/settings/providers/gateway",
            json={
                "provider_id": "local",
                "display_name": "Gateway",
                "endpoint": ENDPOINT,
                "credential_reference": None,
                "enabled": False,
            },
        )
        assert disabled.status_code == 200, disabled.text
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.CONFIGURATION_INVALID
    assert calls == []


def test_a_disabled_runtime_fails_before_the_provider(tmp_path, monkeypatch):
    """An unusable runtime is not a configuration error.

    The execution configuration is well formed; the runtime behind it cannot be
    used. Reporting ``configuration_invalid`` would send the user to edit
    settings that are already correct.
    """
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        client.put("/settings/runtimes/configured-runtime", json={"display_name": "Runtime", "enabled": False})
        payload = _failed_payload(client)

    assert payload["error_code"] == FailureCode.RUNTIME_UNAVAILABLE
    assert calls == []


# ============================================================
# BEGIN: Cancellation and Interruption Are Not Failures
# ============================================================


def test_a_successful_run_carries_no_failure_payload(tmp_path, monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "PONG"}}]})

    with TestClient(_app_with_provider(tmp_path, monkeypatch, responder)) as client:
        _configure(client)
        accepted = client.post("/runs", json={"prompt": "hello"}).json()
        events = client.get(f"/runs/{accepted['run_id']}/events").json()

    assert [e["event_type"] for e in events] == [
        "run_started", "message_started", "message_content", "run_completed",
    ]


def test_every_public_code_has_a_safe_message_and_a_recoverability_decision() -> None:
    """The taxonomy cannot grow a code the UI could not present."""
    from ava.contracts.failures import failure_recoverable

    for code in FailureCode:
        message = PUBLIC_FAILURE_MESSAGES[code]
        assert message and message.strip()
        assert isinstance(failure_recoverable(code), bool)
        # Safe wording never embeds an endpoint, a path, or a secret marker.
        assert "http" not in message.lower()
        assert SECRET not in message
