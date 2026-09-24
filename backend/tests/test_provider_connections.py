"""Phase 5.2 provider-connection domain and architecture guards."""

import inspect

import pytest

from ava.models.provider_connections import ProviderConnection
from ava.services.run_service import RunService


def test_provider_connection_preserves_distinct_connection_and_provider_identities() -> None:
    connection = ProviderConnection(
        provider_connection_id="local-ollama",
        provider_id="openai-compatible",
        display_name="Local Ollama",
        endpoint="http://localhost:11434/v1",
        enabled=True,
        credential_reference="env:OLLAMA_API_KEY",
    )

    assert connection.provider_connection_id == "local-ollama"
    assert connection.provider_id == "openai-compatible"
    assert connection.provider_connection_id != connection.provider_id
    assert connection.enabled is True
    assert connection.credential_reference == "env:OLLAMA_API_KEY"


def test_provider_connection_supports_an_endpointless_connection_without_a_credential() -> None:
    connection = ProviderConnection(
        provider_connection_id="managed-inference",
        provider_id="managed",
        display_name="Managed inference",
    )

    assert connection.endpoint is None
    assert connection.credential_reference is None
    assert connection.enabled is True


def test_provider_connection_rejects_an_adapter_id_reused_as_a_connection_id() -> None:
    with pytest.raises(ValueError, match="distinct"):
        ProviderConnection(
            provider_connection_id="openai-compatible",
            provider_id="openai-compatible",
            display_name="Local Ollama",
        )


def test_provider_connection_requires_an_explicit_boolean_enabled_state() -> None:
    with pytest.raises(ValueError, match="enabled"):
        ProviderConnection(
            provider_connection_id="local-ollama",
            provider_id="openai-compatible",
            display_name="Local Ollama",
            enabled="yes",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_connection_id", ""),
        ("provider_connection_id", "  "),
        ("provider_id", ""),
        ("provider_id", "  "),
        ("display_name", ""),
        ("display_name", "  "),
        ("endpoint", "  "),
        ("credential_reference", "  "),
    ],
)
def test_provider_connection_rejects_blank_identity_and_optional_values(field: str, value: str) -> None:
    values: dict[str, object] = {
        "provider_connection_id": "local-ollama",
        "provider_id": "openai-compatible",
        "display_name": "Local Ollama",
        "endpoint": None,
        "credential_reference": None,
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        ProviderConnection(**values)  # type: ignore[arg-type]


def test_provider_connection_has_no_model_identity_secret_or_sdk_fields() -> None:
    fields = set(ProviderConnection.__dataclass_fields__)

    assert fields == {
        "provider_connection_id",
        "provider_id",
        "display_name",
        "endpoint",
        "enabled",
        "credential_reference",
    }
    assert not fields & {"model_id", "provider_model_name", "api_key", "password", "token"}


def test_run_service_remains_independent_of_provider_connections() -> None:
    assert "ProviderConnection" not in inspect.getsource(RunService)
