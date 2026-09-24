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
from ava.contracts.models import ModelCapabilities, ModelHostingMode, QualificationStatus
from ava.contracts.responses import ModelDiscoveryResponse
from ava.contracts.version import CONTRACT_VERSION
from ava.models.model_registry import ModelProfile, ModelRegistry
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
