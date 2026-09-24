"""Workspace discovery tests (Step 32 backend discovery API).

Covers the metadata-only ``GET /workspaces`` endpoint and its discovery
service: empty registries are truthful, registered workspaces expose only
public-safe identity metadata, serialized responses can never leak internal
paths or permissions, and discovery shares the exact registry instance that
resolution honors (no accidental dual registries).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.contracts.responses import WorkspaceDiscoveryResponse
from ava.contracts.version import CONTRACT_VERSION
from ava.services.workspace_discovery_service import WorkspaceDiscoveryService
from ava.workspaces import (
    ResolvedWorkspace,
    WorkspaceInfo,
    WorkspaceKind,
    WorkspacePermissions,
    WorkspaceRegistry,
    WorkspaceResolver,
)

#: Internal field/key names that must never appear in any discovery payload.
_FORBIDDEN_KEYS = (
    "root_path",
    "local_path",
    "working_dir",
    "resolved_path",
    "canonical_path",
    "permissions",
)


def _local_workspace(
    workspace_id: str,
    *,
    display_name: str | None = None,
    root_path: Path = Path("/srv/ava/workspaces/unused"),
) -> ResolvedWorkspace:
    """Build a test-only resolved workspace with a callable-safe display name."""
    return ResolvedWorkspace(
        info=WorkspaceInfo(
            workspace_id=workspace_id,
            display_name=display_name or workspace_id,
            kind=WorkspaceKind.LOCAL,
        ),
        root_path=root_path,
        permissions=WorkspacePermissions(),
    )


# ============================================================
# BEGIN: Service Tests
# ============================================================


def test_discovery_empty_registry_is_truthful() -> None:
    """An empty registry yields no workspace items and no exception."""
    response = WorkspaceDiscoveryService(registry=WorkspaceRegistry()).discover()

    assert isinstance(response, WorkspaceDiscoveryResponse)
    assert response.workspaces == []
    assert response.contract_version == CONTRACT_VERSION


def test_discovery_exposes_only_public_identity_and_kind() -> None:
    """Registered workspaces surface id, display name, and kind only."""
    registry = WorkspaceRegistry()
    registry.register(_local_workspace("temporary-test", display_name="Temporary Test"))
    registry.register(_local_workspace("project-test", display_name="Project Test"))

    response = WorkspaceDiscoveryService(registry=registry).discover()

    items = [(w.workspace_id, w.display_name, w.kind) for w in response.workspaces]
    assert items == [
        ("temporary-test", "Temporary Test", WorkspaceKind.LOCAL),
        ("project-test", "Project Test", WorkspaceKind.LOCAL),
    ]


def test_discovery_preserves_deterministic_registry_order() -> None:
    """Workspaces are reported in registry insertion order."""
    registry = WorkspaceRegistry()
    for workspace_id in ("z-last", "a-first", "m-middle"):
        registry.register(_local_workspace(workspace_id))

    response = WorkspaceDiscoveryService(registry=registry).discover()

    assert [w.workspace_id for w in response.workspaces] == [
        "z-last",
        "a-first",
        "m-middle",
    ]


def test_discovery_return_value_never_contains_internal_paths(tmp_path: Path) -> None:
    """Discovery values carry only WorkspaceInfo, never ResolvedWorkspace fields."""
    registry = WorkspaceRegistry()
    registry.register(
        _local_workspace("project-test", root_path=tmp_path / "hidden" / "internal")
    )

    response = WorkspaceDiscoveryService(registry=registry).discover()

    payload = response.model_dump(mode="json")
    assert isinstance(payload["workspaces"][0], dict)
    assert set(payload["workspaces"][0]) == {"workspace_id", "display_name", "kind"}
    assert all(key not in payload for key in _FORBIDDEN_KEYS)
    assert "hidden" not in str(payload)


def test_discovery_creates_no_directories(tmp_path: Path) -> None:
    """Discovery describes registrations; it never provisions ephemeral dirs."""
    target = tmp_path / "would-be-ephemeral"
    registry = WorkspaceRegistry()
    registry.register(_local_workspace("temporary-test", root_path=target))

    response = WorkspaceDiscoveryService(registry=registry).discover()

    assert response.workspaces[0].workspace_id == "temporary-test"
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_discovery_is_read_only_over_registry() -> None:
    """Discovery needs only list()/get(); it never registers or mutates."""

    class _ReadOnlyRegistry:
        """Minimal registry stand-in exposing only the reads the service uses."""

        def __init__(self) -> None:
            self._items = {"project-test": _local_workspace("project-test")}

        def list(self) -> list[str]:
            return list(self._items)

        def get(self, workspace_id: str) -> ResolvedWorkspace | None:
            return self._items.get(workspace_id)

    response = WorkspaceDiscoveryService(registry=_ReadOnlyRegistry()).discover()  # type: ignore[arg-type]
    assert [w.workspace_id for w in response.workspaces] == ["project-test"]


def test_discovery_and_resolution_share_the_same_registry() -> None:
    """Resolver and discovery observe one shared registration source."""
    registry = WorkspaceRegistry()
    resolver = WorkspaceResolver(registry)
    service = WorkspaceDiscoveryService(registry=registry)

    registry.register(_local_workspace("project-test"))
    assert resolver.resolve("project-test").info.workspace_id == "project-test"
    assert [w.workspace_id for w in service.discover().workspaces] == ["project-test"]

    registry.register(_local_workspace("temporary-test"))
    assert resolver.resolve("temporary-test").info.workspace_id == "temporary-test"
    assert [w.workspace_id for w in service.discover().workspaces] == [
        "project-test",
        "temporary-test",
    ]


# ============================================================
# END: Service Tests
# ============================================================


# ============================================================
# BEGIN: Route Tests
# ============================================================


def test_workspaces_endpoint_empty_registry() -> None:
    """GET /workspaces returns 200 with an empty list on a fresh app."""
    with TestClient(create_app()) as client:
        response = client.get("/workspaces")

    assert response.status_code == 200
    assert response.json() == {"contract_version": CONTRACT_VERSION, "workspaces": []}


def test_workspaces_endpoint_registered_metadata() -> None:
    """Registered workspaces return id/display_name/kind in registration order."""
    app = create_app()
    with TestClient(app) as client:
        app.state.workspace_registry.register(_local_workspace("temporary-test", display_name="Temporary Test"))
        app.state.workspace_registry.register(_local_workspace("project-test", display_name="Project Test"))
        response = client.get("/workspaces")

    assert response.status_code == 200
    body = response.json()
    assert [item["workspace_id"] for item in body["workspaces"]] == [
        "temporary-test",
        "project-test",
    ]
    assert [item["display_name"] for item in body["workspaces"]] == [
        "Temporary Test",
        "Project Test",
    ]
    assert [item["kind"] for item in body["workspaces"]] == ["local", "local"]


def test_workspaces_endpoint_is_typed_discovery_response() -> None:
    """The route returns the typed WorkspaceDiscoveryResponse contract."""
    app = create_app()
    with TestClient(app) as client:
        app.state.workspace_registry.register(_local_workspace("project-test"))
        response = client.get("/workspaces")

    assert response.status_code == 200
    parsed = WorkspaceDiscoveryResponse.model_validate(response.json())
    assert parsed.workspaces[0].workspace_id == "project-test"


def test_workspaces_endpoint_never_leaks_internal_fields(tmp_path: Path) -> None:
    """Serialized responses cannot contain internal path or permission fields."""
    hidden = tmp_path / "secret" / "host" / "path"
    app = create_app()
    with TestClient(app) as client:
        app.state.workspace_registry.register(
            _local_workspace("project-test", root_path=hidden)
        )
        response = client.get("/workspaces")

    assert response.status_code == 200
    text = response.text
    for key in _FORBIDDEN_KEYS:
        assert key not in text, f"internal field leaked: {key}"
    assert str(hidden) not in text
    assert "secret" not in text
    assert set(response.json()["workspaces"][0]) == {
        "workspace_id",
        "display_name",
        "kind",
    }


def test_workspaces_endpoint_openapi_schema_is_network_safe() -> None:
    """The generated OpenAPI schema for the workspace item has no path fields."""
    app = create_app()
    with TestClient(app):
        schema = app.openapi()

    assert "/workspaces" in schema["paths"]
    assert schema["paths"]["/workspaces"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("WorkspaceDiscoveryResponse")
    props = set(schema["components"]["schemas"]["WorkspaceInfo"]["properties"])
    assert props == {"workspace_id", "display_name", "kind"}
    for key in _FORBIDDEN_KEYS:
        assert key not in schema["components"]["schemas"]["WorkspaceInfo"]["properties"]


def test_workspaces_endpoint_shares_resolution_registry() -> None:
    """Route discovery and app resolution observe the same registration source."""
    app = create_app()
    with TestClient(app) as client:
        app.state.workspace_registry.register(_local_workspace("project-test"))
        response = client.get("/workspaces")
        resolved = app.state.workspace_resolver.resolve("project-test")

    assert [w["workspace_id"] for w in response.json()["workspaces"]] == ["project-test"]
    assert resolved.info.workspace_id == "project-test"


# ============================================================
# END: Route Tests
# ============================================================