"""Step 40: model catalog discovery tests (service + ``GET /models``).

Prove the read-only catalog endpoint is truthful, deterministic, and
public-safe:

- the service enumerates ``ModelProfile``s as ``ModelInfo`` sorted by stable
  ``model_id``, independent of composition order;
- disabled models are visible (so tooling can observe them) with
  ``enabled=False``;
- only public-safe metadata is exposed (no provider-native name, credential,
  endpoint, or permission fields);
- the route is registry/service-backed and contacts no provider.
"""

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.contracts.models import ModelCapabilities, ModelHostingMode, QualificationStatus
from ava.contracts.responses import ModelDiscoveryResponse
from ava.contracts.version import CONTRACT_VERSION
from ava.models.model_configurations import ModelConfiguration
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.provider_connections import ProviderConnection
from ava.models.qualifications import ModelQualification, ModelQualificationStore
from ava.services.model_discovery_service import ModelDiscoveryService

#: Internal field/key names that must never appear in a discovery payload.
_FORBIDDEN_KEYS = (
    "provider_model_name",
    "api_key",
    "credential",
    "token",
    "endpoint",
    "base_url",
    "protocol",
    "permissions",
)


def _profile(
    model_id: str,
    provider_id: str = "local",
    *,
    enabled: bool = True,
    hosting_mode: ModelHostingMode = ModelHostingMode.LOCAL,
) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=f"Display {model_id}",
        provider_id=provider_id,
        provider_model_name=f"{model_id}-native",
        hosting_mode=hosting_mode,
        capabilities=ModelCapabilities(chat=True),
        enabled=enabled,
    )


# ============================================================
# BEGIN: Service Tests
# ============================================================


def test_discovery_empty_registry_is_truthful() -> None:
    response = ModelDiscoveryService(registry=ModelRegistry([])).discover()
    assert isinstance(response, ModelDiscoveryResponse)
    assert response.models == []
    assert response.contract_version == CONTRACT_VERSION


def test_discovery_sorts_by_model_id_independent_of_insertion_order() -> None:
    registry = ModelRegistry([_profile("z-last"), _profile("a-first"), _profile("m-middle")])
    response = ModelDiscoveryService(registry=registry).discover()
    assert [m.model_id for m in response.models] == ["a-first", "m-middle", "z-last"]


def test_discovery_exposes_only_public_metadata() -> None:
    registry = ModelRegistry([_profile("ava/one", provider_id="shared")])
    response = ModelDiscoveryService(registry=registry).discover()

    item = response.models[0]
    assert item.model_id == "ava/one"
    assert item.provider_name == "shared"
    assert item.provider_id == "shared"
    assert item.display_name == "Display ava/one"
    assert item.hosting_mode is ModelHostingMode.LOCAL
    assert item.enabled is True
    assert item.capabilities == ModelCapabilities(chat=True)

    payload = response.model_dump(mode="json")
    serialized = payload["models"][0]
    assert set(serialized) == set(
        {
            "provider_name",
            "model_id",
            "display_name",
            "context_limit",
            "capabilities",
            "provider_id",
            "hosting_mode",
            "enabled",
            "qualifications",
            "contract_version",
        }
    )
    for key in _FORBIDDEN_KEYS:
        assert key not in serialized


def test_discovery_includes_disabled_models_with_flag() -> None:
    registry = ModelRegistry([_profile("ava/on"), _profile("ava/off", enabled=False)])
    response = ModelDiscoveryService(registry=registry).discover()
    assert [(m.model_id, m.enabled) for m in response.models] == [
        ("ava/off", False),
        ("ava/on", True),
    ]


def test_discovery_return_value_never_contains_provider_native_name() -> None:
    registry = ModelRegistry([_profile("ava/secretive")])
    payload = ModelDiscoveryService(registry=registry).discover().model_dump(mode="json")
    assert "ava/secretive-native" not in str(payload)


def test_discovery_exposes_safe_qualifications_in_deterministic_order() -> None:
    registry = ModelRegistry([_profile("ava/one")])
    store = ModelQualificationStore(
        registry,
        (
            ModelQualification(
                model_id="ava/one",
                qualification_id="z",
                status=QualificationStatus.PASS,
                task_class="tool_calling",
                runtime_id="native",
                evidence_summary="Native call observed.",
            ),
            ModelQualification(
                model_id="ava/one",
                qualification_id="a",
                status=QualificationStatus.NOT_TESTED,
                task_class="coding",
                runtime_id=None,
            ),
        ),
    )

    item = ModelDiscoveryService(registry=registry, qualification_store=store).discover().models[0]

    assert [(q.task_class, q.runtime_id, q.qualification_id, q.status) for q in item.qualifications] == [
        ("coding", None, "a", QualificationStatus.NOT_TESTED),
        ("tool_calling", "native", "z", QualificationStatus.PASS),
    ]
    assert item.qualifications[1].evidence_summary == "Native call observed."


def test_discovery_empty_evidence_is_distinct_from_not_tested() -> None:
    registry = ModelRegistry([_profile("ava/one"), _profile("ava/two")])
    store = ModelQualificationStore(
        registry,
        (
            ModelQualification(
                model_id="ava/two",
                qualification_id="chat",
                status=QualificationStatus.NOT_TESTED,
                task_class="chat",
            ),
        ),
    )

    models = ModelDiscoveryService(registry=registry, qualification_store=store).discover().models

    assert models[0].qualifications == []
    assert models[1].qualifications[0].status is QualificationStatus.NOT_TESTED


# ============================================================
# END: Service Tests
# ============================================================


# ============================================================
# BEGIN: Route Tests
# ============================================================


def test_models_endpoint_returns_configured_bootstrap_model() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/models")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert len(body["models"]) == 1
    model = body["models"][0]
    assert model["model_id"] == "local-local-model"
    assert model["provider_id"] == "local"
    assert model["provider_name"] == "local"
    assert model["hosting_mode"] == "local"
    assert model["enabled"] is True


def test_models_endpoint_is_typed_discovery_response() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/models")

    parsed = ModelDiscoveryResponse.model_validate(response.json())
    assert parsed.models[0].model_id == "local-local-model"


def test_models_endpoint_reports_registered_catalog_sorted() -> None:
    app = create_app()
    app.state.model_registry = ModelRegistry([_profile("ava/z"), _profile("ava/a", provider_id="other")])
    app.state.model_discovery_service = ModelDiscoveryService(registry=app.state.model_registry)
    with TestClient(app) as client:
        response = client.get("/models")

    body = response.json()
    assert [m["model_id"] for m in body["models"]] == ["ava/a", "ava/z"]
    assert [m["provider_id"] for m in body["models"]] == ["other", "local"]


def test_models_endpoint_never_leaks_internal_fields() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/models")

    text = response.text
    for key in _FORBIDDEN_KEYS:
        assert key not in text, f"internal field leaked: {key}"
    assert "local-model-native" not in text


def test_models_endpoint_openapi_schema_is_public_safe() -> None:
    app = create_app()
    with TestClient(app):
        schema = app.openapi()

    assert "/models" in schema["paths"]
    ref = schema["paths"]["/models"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ModelDiscoveryResponse")
    props = set(schema["components"]["schemas"]["ModelInfo"]["properties"])
    assert {
        "provider_name",
        "model_id",
        "display_name",
        "capabilities",
        "provider_id",
        "hosting_mode",
        "enabled",
    } <= props
    for key in _FORBIDDEN_KEYS:
        assert key not in props


def test_models_endpoint_is_independent_of_model_providers_endpoint() -> None:
    with TestClient(create_app()) as client:
        models = client.get("/models")
        providers = client.get("/model-providers")

    assert models.status_code == 200
    assert providers.status_code == 200
    assert "providers" in providers.json()
    assert "models" in models.json()


# ============================================================
# END: Route Tests
# ============================================================


# ============================================================
# Configured models (persisted ModelConfiguration records)
# ============================================================


def _configuration(
    model_id: str,
    provider_connection_id: str = "gateway",
    *,
    provider_model_name: str | None = None,
    display_name: str | None = None,
    enabled: bool = True,
) -> ModelConfiguration:
    return ModelConfiguration(
        model_id=model_id,
        provider_connection_id=provider_connection_id,
        provider_model_name=provider_model_name or f"{model_id}-native",
        display_name=display_name or f"Configured {model_id}",
        hosting_mode=ModelHostingMode.LOCAL,
        capabilities=ModelCapabilities(chat=True),
        enabled=enabled,
    )


def _repository(items):
    """A read-only stand-in exposing only what discovery consumes."""

    class _Repo:
        def get(self, key):
            return next(
                (
                    i
                    for i in items
                    if key in (getattr(i, "model_id", None), getattr(i, "provider_connection_id", None))
                ),
                None,
            )

        def list(self):
            return list(items)

    return _Repo()


def _connection(provider_connection_id: str = "gateway", *, provider_id: str = "local") -> ProviderConnection:
    return ProviderConnection(
        provider_connection_id=provider_connection_id,
        provider_id=provider_id,
        display_name="Gateway",
        endpoint="https://configured.test/v1",
    )


def test_configured_models_are_discovered_alongside_registry_profiles() -> None:
    registry = ModelRegistry([_profile("bootstrap-only")])
    service = ModelDiscoveryService(
        registry=registry,
        model_configurations=_repository([_configuration("qwen25-coder-7b")]),
        provider_connections=_repository([_connection()]),
    )

    by_id = {m.model_id: m for m in service.discover().models}
    assert set(by_id) == {"bootstrap-only", "qwen25-coder-7b"}
    assert by_id["qwen25-coder-7b"].display_name == "Configured qwen25-coder-7b"
    assert by_id["qwen25-coder-7b"].provider_id == "local"
    assert by_id["qwen25-coder-7b"].enabled is True


def test_several_configured_models_on_one_provider_stay_distinct() -> None:
    # The defect: the composer was provider-keyed, so one provider could only ever
    # offer one model. Each configured record must keep its own stable id.
    service = ModelDiscoveryService(
        registry=ModelRegistry([]),
        model_configurations=_repository(
            [_configuration("qwen25-coder-7b"), _configuration("qwen35-9b"), _configuration("granite-8b")]
        ),
        provider_connections=_repository([_connection()]),
    )

    response = service.discover()
    assert [m.model_id for m in response.models] == ["granite-8b", "qwen25-coder-7b", "qwen35-9b"]
    assert {m.provider_id for m in response.models} == {"local"}


def test_configured_display_name_is_never_the_provider_native_name() -> None:
    service = ModelDiscoveryService(
        registry=ModelRegistry([]),
        model_configurations=_repository(
            [_configuration("m", provider_model_name="vendor/secret-native", display_name="Friendly")]
        ),
        provider_connections=_repository([_connection()]),
    )

    payload = service.discover().model_dump(mode="json")
    serialized = payload["models"][0]
    assert serialized["display_name"] == "Friendly"
    for key in _FORBIDDEN_KEYS:
        assert key not in serialized
    assert "vendor/secret-native" not in str(payload)


def test_disabled_configured_model_is_discovered_and_flagged() -> None:
    service = ModelDiscoveryService(
        registry=ModelRegistry([]),
        model_configurations=_repository([_configuration("off", enabled=False)]),
        provider_connections=_repository([_connection()]),
    )

    assert [(m.model_id, m.enabled) for m in service.discover().models] == [("off", False)]


def test_a_configured_record_wins_an_id_collision_with_a_registry_profile() -> None:
    # The persisted record is the user's truth, so it must not be shadowed by a
    # bootstrap profile that happens to reuse the id.
    service = ModelDiscoveryService(
        registry=ModelRegistry([_profile("shared-id")]),
        model_configurations=_repository([_configuration("shared-id", display_name="Configured Wins")]),
        provider_connections=_repository([_connection()]),
    )

    response = service.discover()
    assert [m.model_id for m in response.models] == ["shared-id"]
    assert response.models[0].display_name == "Configured Wins"


def test_discovery_reports_which_model_the_application_default_selects() -> None:
    defaults = ApplicationExecutionDefaults(
        default_provider_connection_id="gateway",
        default_model_id="qwen35-9b",
        default_runtime_configuration_id="native",
    )

    class _Defaults:
        def get(self):
            return defaults

    service = ModelDiscoveryService(
        registry=ModelRegistry([]),
        model_configurations=_repository([_configuration("qwen25-coder-7b"), _configuration("qwen35-9b")]),
        provider_connections=_repository([_connection()]),
        execution_defaults=_Defaults(),
    )

    assert service.discover().default_model_id == "qwen35-9b"


def test_default_model_id_is_null_when_no_defaults_are_configured() -> None:
    service = ModelDiscoveryService(registry=ModelRegistry([_profile("a")]))
    assert service.discover().default_model_id is None


def test_default_model_id_is_reported_even_if_the_model_is_not_in_the_catalog() -> None:
    # A dangling default is a configuration problem the user should be able to
    # see, not a reason to hide the fact that one is configured.
    defaults = ApplicationExecutionDefaults(
        default_provider_connection_id="gateway",
        default_model_id="deleted-model",
        default_runtime_configuration_id="native",
    )

    class _Defaults:
        def get(self):
            return defaults

    service = ModelDiscoveryService(
        registry=ModelRegistry([]),
        model_configurations=_repository([_configuration("present")]),
        provider_connections=_repository([_connection()]),
        execution_defaults=_Defaults(),
    )

    assert service.discover().default_model_id == "deleted-model"
