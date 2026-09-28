"""Settings API tests (Phase 5.10).

API-level coverage for ``/settings/*``: the persisted configuration boundary.
These tests assert three things beyond ordinary CRUD shape — that identity and
immutable associations cannot be silently rewritten, that ``credential_reference``
is validated for syntax but never resolved, and that no response can carry
secret material.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.version import CONTRACT_VERSION

SECRET = "sk-live-DO-NOT-LEAK-0123456789"
VARIABLE = "OPENAI_API_KEY"

# ============================================================
# BEGIN: Helpers
# ============================================================


@pytest.fixture
def client() -> Any:
    """A client over an isolated in-memory configuration store.

    Persistence is selected explicitly rather than inherited from the ambient
    environment, so these tests assert on the configuration they themselves
    wrote. Without the override, a repository-root ``.env`` selecting
    relational persistence would share one on-disk database across every test
    in the process and configured records would leak between them.
    """
    app = create_app(settings=Settings(persistence_provider="memory"))
    with TestClient(app) as test_client:
        yield test_client


def _create_connection(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider_connection_id": "conn-1",
        "provider_id": "openai-compatible",
        "display_name": "Primary gateway",
        "endpoint": "https://gateway.internal/v1",
    }
    payload.update(overrides)
    response = client.post("/settings/providers", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _create_model(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_id": "model-1",
        "provider_connection_id": "conn-1",
        "provider_model_name": "gpt-x",
        "display_name": "Gateway model",
        "hosting_mode": "company_hosted",
    }
    payload.update(overrides)
    response = client.post("/settings/models", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _create_runtime(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_configuration_id": "runtime-native",
        "runtime_type": "native",
        "display_name": "Native",
    }
    payload.update(overrides)
    response = client.post("/settings/runtimes", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _update_connection(client: TestClient, connection_id: str, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "display_name": "Primary gateway",
        "endpoint": "https://gateway.internal/v1",
        "enabled": True,
        "credential_reference": None,
    }
    payload.update(overrides)
    return client.put(f"/settings/providers/{connection_id}", json=payload)


def _update_model(client: TestClient, model_id: str, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "provider_model_name": "gpt-x",
        "display_name": "Gateway model",
        "hosting_mode": "company_hosted",
        "capabilities": {"chat": True},
        "enabled": True,
    }
    payload.update(overrides)
    return client.put(f"/settings/models/{model_id}", json=payload)


def _update_runtime(client: TestClient, runtime_id: str, **overrides: Any) -> Any:
    payload: dict[str, Any] = {"display_name": "Native", "enabled": True}
    payload.update(overrides)
    return client.put(f"/settings/runtimes/{runtime_id}", json=payload)


def _set_defaults(client: TestClient, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "default_provider_connection_id": "conn-1",
        "default_model_id": "model-1",
        "default_runtime_configuration_id": "runtime-native",
    }
    payload.update(overrides)
    return client.put("/settings/defaults", json=payload)


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Provider Connections
# ============================================================


def test_provider_list_is_empty_before_anything_is_configured(client: TestClient) -> None:
    response = client.get("/settings/providers")
    assert response.status_code == 200
    assert response.json() == {
        "provider_connections": [],
        "contract_version": CONTRACT_VERSION,
    }


def test_provider_create_returns_201_and_the_configured_fields(client: TestClient) -> None:
    body = _create_connection(
        client,
        credential_reference=f"env:{VARIABLE}",
    )
    assert set(body) == {
        "provider_connection_id",
        "provider_id",
        "display_name",
        "endpoint",
        "enabled",
        "credential_reference",
        "contract_version",
    }
    assert body["provider_connection_id"] == "conn-1"
    assert body["enabled"] is True
    assert body["credential_reference"] == f"env:{VARIABLE}"


def test_provider_create_accepts_null_endpoint_and_null_credential_reference(
    client: TestClient,
) -> None:
    """A local unauthenticated provider legitimately has neither."""
    body = _create_connection(client, endpoint=None, credential_reference=None)
    assert body["endpoint"] is None
    assert body["credential_reference"] is None


def test_provider_get_returns_the_stored_connection(client: TestClient) -> None:
    _create_connection(client)
    response = client.get("/settings/providers/conn-1")
    assert response.status_code == 200
    assert response.json()["display_name"] == "Primary gateway"


def test_provider_get_unknown_is_404(client: TestClient) -> None:
    response = client.get("/settings/providers/nope")
    assert response.status_code == 404
    assert response.json()["error_code"] == "provider_connection_not_found"
    assert response.json()["category"] == "not_found"


def test_provider_update_replaces_mutable_fields(client: TestClient) -> None:
    _create_connection(client)
    response = _update_connection(
        client, "conn-1", display_name="Renamed", enabled=False, endpoint="https://other/v1"
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["enabled"] is False
    assert response.json()["endpoint"] == "https://other/v1"


def test_provider_update_clears_nullable_fields_with_explicit_null(client: TestClient) -> None:
    _create_connection(client, credential_reference=f"env:{VARIABLE}")
    response = _update_connection(client, "conn-1", endpoint=None, credential_reference=None)
    assert response.status_code == 200
    assert response.json()["endpoint"] is None
    assert response.json()["credential_reference"] is None


def test_provider_duplicate_is_409(client: TestClient) -> None:
    _create_connection(client)
    response = client.post(
        "/settings/providers",
        json={
            "provider_connection_id": "conn-1",
            "provider_id": "openai-compatible",
            "display_name": "Duplicate",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "provider_connection_already_exists"


def test_provider_update_of_unknown_is_404(client: TestClient) -> None:
    assert _update_connection(client, "nope").status_code == 404


def test_provider_rejects_changing_the_immutable_provider_association(client: TestClient) -> None:
    _create_connection(client)
    response = _update_connection(client, "conn-1", provider_id="local")
    assert response.status_code == 409
    assert response.json()["error_code"] == "provider_connection_field_immutable"
    assert client.get("/settings/providers/conn-1").json()["provider_id"] == "openai-compatible"


def test_provider_accepts_resending_the_current_provider_association(client: TestClient) -> None:
    """A client that round-trips a full record is not punished for it."""
    _create_connection(client)
    response = _update_connection(client, "conn-1", provider_id="openai-compatible")
    assert response.status_code == 200


def test_provider_list_includes_disabled_records(client: TestClient) -> None:
    _create_connection(client)
    _create_connection(
        client, provider_connection_id="conn-2", display_name="Disabled", enabled=False
    )
    listed = client.get("/settings/providers").json()["provider_connections"]
    assert [item["provider_connection_id"] for item in listed] == ["conn-1", "conn-2"]
    assert listed[1]["enabled"] is False


def test_provider_can_be_disabled_and_re_enabled(client: TestClient) -> None:
    _create_connection(client)
    assert _update_connection(client, "conn-1", enabled=False).json()["enabled"] is False
    assert _update_connection(client, "conn-1", enabled=True).json()["enabled"] is True


@pytest.mark.parametrize(
    "reference", ["env:OPENAI_API_KEY", "aws-secrets:prod/openai", "azure-keyvault:ava"]
)
def test_provider_accepts_well_formed_credential_references(client: TestClient, reference: str) -> None:
    """Syntax is validated; the referenced secret need not exist."""
    body = _create_connection(client, credential_reference=reference)
    assert body["credential_reference"] == reference


@pytest.mark.parametrize(
    "reference", ["OPENAI_API_KEY", "env:", ":NAME", "   ", "env:   "]
)
def test_provider_rejects_malformed_credential_references(client: TestClient, reference: str) -> None:
    response = client.post(
        "/settings/providers",
        json={
            "provider_connection_id": "conn-bad",
            "provider_id": "openai-compatible",
            "display_name": "Bad",
            "credential_reference": reference,
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_provider_connection"


def test_provider_does_not_require_the_referenced_secret_to_resolve(client: TestClient) -> None:
    """A save must not depend on transient secret-backend availability."""
    _create_connection(client, credential_reference="env:AVA_DEFINITELY_UNSET_VARIABLE")
    assert client.get("/settings/providers/conn-1").status_code == 200


def test_provider_rejects_blank_required_fields_with_422(client: TestClient) -> None:
    response = client.post(
        "/settings/providers",
        json={"provider_connection_id": "  ", "provider_id": "x", "display_name": "y"},
    )
    assert response.status_code == 422


# ============================================================
# END: Provider Connections
# ============================================================


# ============================================================
# BEGIN: Model Configurations
# ============================================================


def test_model_list_is_empty_before_anything_is_configured(client: TestClient) -> None:
    response = client.get("/settings/models")
    assert response.status_code == 200
    assert response.json() == {"models": [], "contract_version": CONTRACT_VERSION}


def test_model_create_returns_201_and_the_configured_fields(client: TestClient) -> None:
    _create_connection(client)
    body = _create_model(client)
    assert set(body) == {
        "model_id",
        "provider_connection_id",
        "provider_model_name",
        "display_name",
        "hosting_mode",
        "capabilities",
        "enabled",
        "contract_version",
    }
    assert body["hosting_mode"] == "company_hosted"


def test_model_create_rejects_an_unknown_provider_connection(client: TestClient) -> None:
    """A model is never given a connection nobody configured."""
    response = client.post(
        "/settings/models",
        json={
            "model_id": "model-1",
            "provider_connection_id": "ghost",
            "provider_model_name": "gpt-x",
            "display_name": "Ghost",
            "hosting_mode": "local",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_model_configuration"
    assert "Unknown provider connection" in response.json()["message"]


def test_model_get_returns_the_stored_configuration(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    response = client.get("/settings/models/model-1")
    assert response.status_code == 200
    assert response.json()["provider_model_name"] == "gpt-x"


def test_model_get_unknown_is_404(client: TestClient) -> None:
    response = client.get("/settings/models/nope")
    assert response.status_code == 404
    assert response.json()["error_code"] == "model_configuration_not_found"


def test_model_update_replaces_mutable_fields(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    response = _update_model(client, "model-1", display_name="Renamed", enabled=False)
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["enabled"] is False


def test_model_duplicate_is_409(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    response = client.post(
        "/settings/models",
        json={
            "model_id": "model-1",
            "provider_connection_id": "conn-1",
            "provider_model_name": "other",
            "display_name": "Duplicate",
            "hosting_mode": "local",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "model_configuration_already_exists"


def test_model_update_of_unknown_is_404(client: TestClient) -> None:
    assert _update_model(client, "nope").status_code == 404


def test_model_rejects_changing_the_immutable_provider_association(client: TestClient) -> None:
    _create_connection(client)
    _create_connection(client, provider_connection_id="conn-2", display_name="Second")
    _create_model(client)
    response = _update_model(client, "model-1", provider_connection_id="conn-2")
    assert response.status_code == 409
    assert response.json()["error_code"] == "model_configuration_field_immutable"
    assert client.get("/settings/models/model-1").json()["provider_connection_id"] == "conn-1"


def test_model_accepts_resending_the_current_provider_association(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    assert _update_model(client, "model-1", provider_connection_id="conn-1").status_code == 200


def test_model_rejects_an_unknown_hosting_mode(client: TestClient) -> None:
    _create_connection(client)
    response = client.post(
        "/settings/models",
        json={
            "model_id": "model-bad",
            "provider_connection_id": "conn-1",
            "provider_model_name": "gpt-x",
            "display_name": "Bad",
            "hosting_mode": "somewhere_else",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("mode", ["local", "company_hosted", "external"])
def test_model_hosting_mode_round_trips(client: TestClient, mode: str) -> None:
    _create_connection(client)
    body = _create_model(client, model_id=f"model-{mode}", hosting_mode=mode)
    assert body["hosting_mode"] == mode
    assert client.get(f"/settings/models/model-{mode}").json()["hosting_mode"] == mode


def test_model_capabilities_round_trip(client: TestClient) -> None:
    _create_connection(client)
    capabilities = {
        "chat": True,
        "streaming": True,
        "tool_calling": False,
        "structured_output": True,
        "vision": False,
        "embeddings": False,
        "reasoning": False,
        "code_specialization": True,
    }
    body = _create_model(client, capabilities=capabilities)
    assert {k: v for k, v in body["capabilities"].items() if k != "contract_version"} == capabilities
    assert client.get("/settings/models/model-1").json()["capabilities"] == body["capabilities"]


def test_model_capabilities_default_to_conservative_values(client: TestClient) -> None:
    _create_connection(client)
    body = _create_model(client)
    assert all(
        value is False
        for key, value in body["capabilities"].items()
        if key != "contract_version"
    )


def test_model_update_replaces_capabilities(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    response = _update_model(client, "model-1", capabilities={"chat": True, "vision": True})
    capabilities = response.json()["capabilities"]
    assert capabilities["chat"] is True
    assert capabilities["vision"] is True
    assert capabilities["embeddings"] is False


def test_model_list_includes_disabled_records(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    _create_model(client, model_id="model-2", provider_model_name="gpt-y", enabled=False)
    listed = client.get("/settings/models").json()["models"]
    assert [item["model_id"] for item in listed] == ["model-1", "model-2"]
    assert listed[1]["enabled"] is False


def test_model_rejects_duplicate_identity_fields(client: TestClient) -> None:
    _create_connection(client)
    response = client.post(
        "/settings/models",
        json={
            "model_id": "conn-1",
            "provider_connection_id": "conn-1",
            "provider_model_name": "gpt-x",
            "display_name": "Same identity",
            "hosting_mode": "local",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_model_configuration"


# ============================================================
# END: Model Configurations
# ============================================================


# ============================================================
# BEGIN: Runtime Configurations
# ============================================================


def test_runtime_list_is_empty_before_anything_is_configured(client: TestClient) -> None:
    response = client.get("/settings/runtimes")
    assert response.status_code == 200
    assert response.json() == {"runtimes": [], "contract_version": CONTRACT_VERSION}


def test_runtime_create_returns_201_and_the_configured_fields(client: TestClient) -> None:
    body = _create_runtime(client)
    assert set(body) == {
        "runtime_configuration_id",
        "runtime_type",
        "display_name",
        "enabled",
        "contract_version",
    }
    assert body["runtime_type"] == "native"


def test_runtime_create_does_not_require_the_adapter_to_be_installed(client: TestClient) -> None:
    """Configuring a runtime must not depend on it being present."""
    body = _create_runtime(client, runtime_configuration_id="runtime-x", runtime_type="not-installed")
    assert body["runtime_type"] == "not-installed"


def test_runtime_get_returns_the_stored_configuration(client: TestClient) -> None:
    _create_runtime(client)
    response = client.get("/settings/runtimes/runtime-native")
    assert response.status_code == 200
    assert response.json()["display_name"] == "Native"


def test_runtime_get_unknown_is_404(client: TestClient) -> None:
    response = client.get("/settings/runtimes/nope")
    assert response.status_code == 404
    assert response.json()["error_code"] == "runtime_configuration_not_found"


def test_runtime_update_replaces_mutable_fields(client: TestClient) -> None:
    _create_runtime(client)
    response = _update_runtime(client, "runtime-native", display_name="Renamed", enabled=False)
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["enabled"] is False


def test_runtime_duplicate_is_409(client: TestClient) -> None:
    _create_runtime(client)
    response = client.post(
        "/settings/runtimes",
        json={
            "runtime_configuration_id": "runtime-native",
            "runtime_type": "openhands",
            "display_name": "Duplicate",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "runtime_configuration_already_exists"


def test_runtime_update_of_unknown_is_404(client: TestClient) -> None:
    assert _update_runtime(client, "nope").status_code == 404


def test_runtime_type_is_immutable_under_the_same_configuration_id(client: TestClient) -> None:
    """``native`` must never be silently re-pointed at ``openhands``."""
    _create_runtime(client)
    response = _update_runtime(client, "runtime-native", runtime_type="openhands")
    assert response.status_code == 409
    assert response.json()["error_code"] == "runtime_configuration_field_immutable"
    assert client.get("/settings/runtimes/runtime-native").json()["runtime_type"] == "native"


def test_runtime_accepts_resending_the_current_runtime_type(client: TestClient) -> None:
    _create_runtime(client)
    assert _update_runtime(client, "runtime-native", runtime_type="native").status_code == 200


def test_runtime_list_includes_disabled_records(client: TestClient) -> None:
    _create_runtime(client)
    _create_runtime(
        client, runtime_configuration_id="runtime-off", display_name="Off", enabled=False
    )
    listed = client.get("/settings/runtimes").json()["runtimes"]
    assert [item["runtime_configuration_id"] for item in listed] == [
        "runtime-native",
        "runtime-off",
    ]
    assert listed[1]["enabled"] is False


def test_runtime_rejects_execution_configuration_fields(client: TestClient) -> None:
    """No model, provider, workspace, tool, or credential field is accepted."""
    for forbidden in ("model_id", "provider_id", "provider_connection_id", "workspace_id"):
        response = client.post(
            "/settings/runtimes",
            json={
                "runtime_configuration_id": f"runtime-{forbidden}",
                "runtime_type": "native",
                "display_name": "Smuggled",
                forbidden: "x",
            },
        )
        assert response.status_code == 422, forbidden
        assert client.get(f"/settings/runtimes/runtime-{forbidden}").status_code == 404


# ============================================================
# END: Runtime Configurations
# ============================================================


# ============================================================
# BEGIN: Application Execution Defaults
# ============================================================


def test_defaults_report_not_configured_rather_than_404(client: TestClient) -> None:
    response = client.get("/settings/defaults")
    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "defaults": None,
        "contract_version": CONTRACT_VERSION,
    }


def test_defaults_set_and_get(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    _create_runtime(client)
    response = _set_defaults(client)
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["defaults"] == {
        "default_provider_connection_id": "conn-1",
        "default_model_id": "model-1",
        "default_runtime_configuration_id": "runtime-native",
        "contract_version": CONTRACT_VERSION,
    }
    assert client.get("/settings/defaults").json() == response.json()


def test_defaults_replace_a_valid_selection(client: TestClient) -> None:
    _create_connection(client)
    _create_connection(client, provider_connection_id="conn-2", display_name="Second")
    _create_model(client)
    _create_model(
        client,
        model_id="model-2",
        provider_connection_id="conn-2",
        provider_model_name="gpt-y",
    )
    _create_runtime(client)
    _set_defaults(client)
    response = _set_defaults(
        client, default_provider_connection_id="conn-2", default_model_id="model-2"
    )
    assert response.status_code == 200
    assert response.json()["defaults"]["default_provider_connection_id"] == "conn-2"


def test_defaults_require_existing_records(client: TestClient) -> None:
    for field in (
        "default_provider_connection_id",
        "default_model_id",
        "default_runtime_configuration_id",
    ):
        response = _set_defaults(client, **{field: "ghost"})
        assert response.status_code == 422, field
        assert response.json()["error_code"] == "invalid_execution_defaults"
    assert client.get("/settings/defaults").json()["configured"] is False


def test_defaults_reject_disabled_records(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    _create_runtime(client)
    for disable in (
        lambda: _update_connection(client, "conn-1", enabled=False),
        lambda: _update_model(client, "model-1", enabled=False),
        lambda: _update_runtime(client, "runtime-native", enabled=False),
    ):
        disable()
        assert _set_defaults(client).status_code == 422


def test_defaults_reject_a_model_from_a_different_connection(client: TestClient) -> None:
    _create_connection(client)
    _create_connection(client, provider_connection_id="conn-2", display_name="Second")
    _create_model(client)
    _create_runtime(client)
    response = _set_defaults(client, default_provider_connection_id="conn-2")
    assert response.status_code == 422
    assert "does not belong" in response.json()["message"]


def test_defaults_do_not_preserve_a_previous_value_after_a_rejected_write(client: TestClient) -> None:
    _create_connection(client)
    _create_model(client)
    _create_runtime(client)
    _set_defaults(client)
    assert _set_defaults(client, default_model_id="ghost").status_code == 422
    assert (
        client.get("/settings/defaults").json()["defaults"]["default_model_id"] == "model-1"
    )


def test_defaults_reject_adapter_keys(client: TestClient) -> None:
    """Defaults reference configured identity, not adapter identity."""
    for forbidden in ("provider_id", "provider_model_name", "runtime_type"):
        response = client.put(
            "/settings/defaults",
            json={
                "default_provider_connection_id": "conn-1",
                "default_model_id": "model-1",
                "default_runtime_configuration_id": "runtime-native",
                forbidden: "x",
            },
        )
        assert response.status_code == 422, forbidden


def test_defaults_require_all_three_references(client: TestClient) -> None:
    response = client.put(
        "/settings/defaults", json={"default_provider_connection_id": "conn-1"}
    )
    assert response.status_code == 422


# ============================================================
# END: Application Execution Defaults
# ============================================================


# ============================================================
# BEGIN: Credential safety
# ============================================================


def test_no_settings_response_contains_resolved_secret_material(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolvable reference still yields only the reference in every response."""
    monkeypatch.setenv(VARIABLE, SECRET)
    _create_connection(client, credential_reference=f"env:{VARIABLE}")
    _create_model(client)
    _create_runtime(client)
    _set_defaults(client)

    bodies = [
        client.get("/settings/providers").text,
        client.get("/settings/providers/conn-1").text,
        client.get("/settings/models").text,
        client.get("/settings/runtimes").text,
        client.get("/settings/defaults").text,
    ]
    for body in bodies:
        assert SECRET not in body


def test_settings_contracts_have_no_secret_bearing_field() -> None:
    from ava.contracts import settings as contracts

    forbidden = {
        "api_key",
        "credential",
        "credential_value",
        "password",
        "token",
        "secret",
        "secret_value",
    }
    for name in dir(contracts):
        attribute = getattr(contracts, name)
        if not hasattr(attribute, "model_fields"):
            continue
        assert forbidden & set(attribute.model_fields) == set(), name


def test_settings_contracts_expose_credential_reference_only(client: TestClient) -> None:
    from ava.contracts import settings as contracts

    fields = set(contracts.ProviderConnectionResponse.model_fields)
    assert "credential_reference" in fields
    assert fields & {"api_key", "secret", "credential", "token", "password"} == set()
    body = _create_connection(client, credential_reference=f"env:{VARIABLE}")
    assert set(body) == set(contracts.ProviderConnectionResponse.model_fields)


def test_settings_openapi_schema_exposes_no_secret_property(client: TestClient) -> None:
    """The generated public schema is the contract clients are built from."""
    schema = json.dumps(client.get("/openapi.json").json())
    for forbidden in ("SecretValue", "api_key", "secret_value", "credential_value"):
        assert forbidden not in schema, forbidden
    assert "credential_reference" in schema


def test_settings_api_never_accepts_a_secret_value_field(client: TestClient) -> None:
    response = client.post(
        "/settings/providers",
        json={
            "provider_connection_id": "conn-leak",
            "provider_id": "openai-compatible",
            "display_name": "Leak attempt",
            "api_key": SECRET,
        },
    )
    assert response.status_code == 422
    assert SECRET not in response.text


# ============================================================
# END: Credential safety
# ============================================================


# ============================================================
# BEGIN: Discovery compatibility
# ============================================================


def test_discovery_routes_keep_their_own_meaning(client: TestClient) -> None:
    """Persisted Settings and discovery are separate boundaries."""
    _create_connection(client, display_name="Configured gateway")
    _create_model(client)
    _create_runtime(client)

    configured_providers = client.get("/settings/providers").json()["provider_connections"]
    discovered_providers = client.get("/model-providers").json()["providers"]
    assert [item["provider_connection_id"] for item in configured_providers] == ["conn-1"]
    assert all("provider_connection_id" not in item for item in discovered_providers)

    configured_runtimes = client.get("/settings/runtimes").json()["runtimes"]
    discovered_runtimes = client.get("/runtimes").json()["runtimes"]
    assert [item["runtime_configuration_id"] for item in configured_runtimes] == ["runtime-native"]
    assert all("runtime_configuration_id" not in item for item in discovered_runtimes)


def test_discovery_routes_do_not_reflect_persisted_configuration(client: TestClient) -> None:
    """Configuring a record must not invent availability."""
    _create_connection(client)
    _create_runtime(client, runtime_configuration_id="runtime-uninstalled", runtime_type="nope")
    discovered = client.get("/runtimes").json()["runtimes"]
    assert "runtime-uninstalled" not in json.dumps(discovered)


def test_capabilities_route_is_unchanged(client: TestClient) -> None:
    response = client.get("/capabilities")
    assert response.status_code == 200
    assert set(response.json()["capabilities"]) >= {"health", "runs"}


def test_settings_do_not_change_run_execution_defaults(client: TestClient) -> None:
    """Persisted defaults are not yet authoritative for execution."""
    _create_connection(client)
    _create_model(client)
    _create_runtime(client)
    _set_defaults(client)
    profiles = client.get("/execution-profiles").json()
    assert profiles["default_profile_id"] == "local-default"
    assert {profile["id"] for profile in profiles["profiles"]} == {
        "local-default",
        "openhands-local",
    }


# ============================================================
# END: Discovery compatibility
# ============================================================
