"""Persistent Workspace access and authority invalidation; no file execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ava.api.routes.workspace_access import create_workspace_access
from ava.contracts.tool_features import UpdateToolFeaturesRequest
from ava.contracts.tool_policy import ToolPolicyRequest
from ava.contracts.tools import (
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolExecutionContext,
    ToolRequest,
    ToolRisk,
)
from ava.contracts.workspace_access import (
    CreateWorkspaceAccessRequest,
    UpdateWorkspaceAccessRequest,
    WorkspaceAccessConfiguration,
    WorkspaceAccessResponse,
    WorkspaceAccessStatus,
)
from ava.infrastructure.composition import create_workspace_access_lookup
from ava.infrastructure.persistence.composition import create_relational_repositories
from ava.repositories.workspace_access_repository import WorkspaceAccessConflictError
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_feature_store import ToolFeatureStore
from ava.services.tool_policy_service import ToolPolicyService
from ava.services.workspace_access_service import (
    WorkspaceAccessService,
)
from ava.services.workspace_access_store import WorkspaceAccessStore
from ava.tools.authority import ToolExecutionAuthority, ToolOperationType
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import WorkspaceKind, bind_workspace
from ava.workspaces.registry import WorkspaceRegistry
from ava.workspaces.resolver import WorkspaceResolver


class Admin:
    def can_manage(self) -> bool:
        return True


class DeniedAdmin:
    def can_manage(self) -> bool:
        return False


class Authority:
    def __init__(self, value: ToolExecutionAuthority) -> None:
        self.value: ToolExecutionAuthority | None = value

    def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
        return self.value if context_ref == "ctx" else None


def create(service: WorkspaceAccessService, workspace_id: str, root: Path) -> WorkspaceAccessResponse:
    return service.create(
        CreateWorkspaceAccessRequest(
            workspace_id=workspace_id,
            name="Test workspace",
            kind=WorkspaceKind.LOCAL,
            root_path=str(root),
            allowed_capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE),
        )
    )


def test_workspace_creation_validation_and_stable_identity(tmp_path: Path) -> None:
    store = WorkspaceAccessStore()
    service = WorkspaceAccessService(store, Admin())
    root = tmp_path / "root"
    root.mkdir()
    created = create(service, "project-root", root)
    assert created.workspaces[0].revision == 1
    assert created.workspaces[0].root_path == str(root.resolve())
    with pytest.raises(ValueError, match="absolute directory"):
        create(service, "relative-root", Path("relative"))
    with pytest.raises(ValueError, match="existing directory"):
        create(service, "missing-root", tmp_path / "missing")
    with pytest.raises(ValueError):
        create(service, "project-root", root)
    with pytest.raises(ValidationError):
        WorkspaceAccessConfiguration(
            workspace_id="../bad",
            kind=WorkspaceKind.LOCAL,
            root_path=str(root),
            revision=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_workspace_configuration_survives_relational_restart(tmp_path: Path) -> None:
    database = str(tmp_path / "workspace.sqlite3")
    root = tmp_path / "authorized"
    root.mkdir()
    first = create_relational_repositories(database)
    service = WorkspaceAccessService(first.workspace_access_repository, Admin())
    create(service, "stable-workspace", root)
    first.dispose()
    second = create_relational_repositories(database)
    try:
        config = second.workspace_access_repository.get("stable-workspace")
        assert config is not None and config.root_path == str(root.resolve())
        assert config.revision == 1 and config.status is WorkspaceAccessStatus.ACTIVE
    finally:
        second.dispose()


def test_revocation_survives_relational_restart(tmp_path: Path) -> None:
    database = str(tmp_path / "revoked.sqlite3")
    root = tmp_path / "authorized"
    root.mkdir()
    first = create_relational_repositories(database)
    service = WorkspaceAccessService(first.workspace_access_repository, Admin())
    create(service, "revoked-root", root)
    service.update(
        "revoked-root",
        UpdateWorkspaceAccessRequest(
            kind=WorkspaceKind.LOCAL,
            root_path=str(root),
            allowed_capabilities=(),
            status=WorkspaceAccessStatus.REVOKED,
            expected_revision=1,
        ),
    )
    first.dispose()
    second = create_relational_repositories(database)
    try:
        configuration = second.workspace_access_repository.get("revoked-root")
        assert configuration is not None and configuration.status is WorkspaceAccessStatus.REVOKED
        lookup = create_workspace_access_lookup(second.workspace_access_repository)
        assert lookup.resolve("revoked-root") == (True, None)
    finally:
        second.dispose()


def test_concurrent_updates_conflict_instead_of_overwriting(tmp_path: Path) -> None:
    store = WorkspaceAccessStore()
    service = WorkspaceAccessService(store, Admin())
    root = tmp_path / "root"
    root.mkdir()
    create(service, "workspace", root)
    original = store.get("workspace")
    assert original is not None
    first = original.model_copy(update={"name": "first", "revision": 2, "updated_at": datetime.now(UTC)})
    second = original.model_copy(update={"name": "second", "revision": 2, "updated_at": datetime.now(UTC)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda value: _cas(store, value), (first, second)))
    assert sorted(outcomes) == ["conflict", "saved"]


def _cas(store: WorkspaceAccessStore, value: WorkspaceAccessConfiguration) -> str:
    try:
        store.compare_and_set(1, value)
        return "saved"
    except WorkspaceAccessConflictError:
        return "conflict"


def test_corrupt_configuration_fails_closed(tmp_path: Path) -> None:
    database = create_relational_repositories(":memory:")
    root = tmp_path / "root"
    root.mkdir()
    create(WorkspaceAccessService(database.workspace_access_repository, Admin()), "workspace", root)
    with database.database.transaction() as connection:
        connection.execute(
            "UPDATE workspace_access_configurations SET allowed_capabilities = ? WHERE workspace_id = ?",
            ("not-json", "workspace"),
        )
    service = WorkspaceAccessService(database.workspace_access_repository, Admin())
    assert service.state().configuration_status == "invalid"
    lookup = create_workspace_access_lookup(database.workspace_access_repository)
    assert lookup.resolve("workspace") == (True, None)
    database.dispose()


def test_revocation_persists_and_removes_workspace_from_resolver(tmp_path: Path) -> None:
    store = WorkspaceAccessStore()
    service = WorkspaceAccessService(store, Admin())
    root = tmp_path / "root"
    root.mkdir()
    create(service, "workspace", root)
    update = UpdateWorkspaceAccessRequest(
        kind=WorkspaceKind.LOCAL,
        root_path=str(root),
        allowed_capabilities=(ToolCapability.FILE_READ,),
        status=WorkspaceAccessStatus.REVOKED,
        expected_revision=1,
    )
    service.update("workspace", update)
    revoked = store.get("workspace")
    assert revoked is not None and revoked.status is WorkspaceAccessStatus.REVOKED
    assert create_workspace_access_lookup(store).resolve("workspace") == (True, None)
    with pytest.raises(ValueError, match="cannot be reactivated"):
        service.update(
            "workspace",
            UpdateWorkspaceAccessRequest(
                kind=WorkspaceKind.LOCAL,
                root_path=str(root),
                status=WorkspaceAccessStatus.ACTIVE,
                expected_revision=2,
            ),
        )


def test_root_or_permission_change_invalidates_existing_authority(tmp_path: Path) -> None:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    (old_root / "source.txt").write_text("old")
    (new_root / "source.txt").write_text("new")
    store = WorkspaceAccessStore()
    admin = WorkspaceAccessService(store, Admin())
    create(admin, "workspace", old_root)
    registry = ToolRegistry()
    definition = ToolDefinition(
        tool_id="files.read",
        name="Read",
        description="Read file",
        tool_version="1",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        required_capabilities=(ToolCapability.FILE_READ,),
        risk=ToolRisk.LOW,
        execution_category=ToolExecutionCategory.DETERMINISTIC,
    )
    registry.register(definition)
    features = ToolFeatureService(registry, ToolFeatureStore(), Admin())
    features.update(
        UpdateToolFeaturesRequest(framework_enabled=True, enabled_tool_ids=("files.read",), expected_version=0)
    )
    resolver = WorkspaceResolver(WorkspaceRegistry(), create_workspace_access_lookup(store))
    initial = resolver.resolve_tool_access("workspace")
    caps = frozenset({ToolCapability.FILE_READ})
    authority = Authority(
        ToolExecutionAuthority(
            context=ToolExecutionContext(
                context_id="ctx",
                workspace_id="workspace",
                workspace_authorization_ref="scope",
                tool_policy_ref="policy",
                caller_authority_ref="caller",
            ),
            workspace=bind_workspace(initial),
            revision_ref="rev-1",
            allowed_tool_ids=frozenset({"files.read"}),
            allowed_capabilities=caps,
            technical_capabilities=caps,
        )
    )
    policy = ToolPolicyService(
        registry, features, resolver, authority=authority, operations={"files.read": ToolOperationType.READ}
    )
    request = ToolPolicyRequest(
        request=ToolRequest(
            invocation_id="invoke",
            tool_id="files.read",
            tool_version="1",
            arguments={"path": "source.txt"},
            execution_context_ref="ctx",
        )
    )
    assert policy.evaluate(request).decision.value == "allow"
    admin.update(
        "workspace",
        UpdateWorkspaceAccessRequest(
            kind=WorkspaceKind.LOCAL,
            root_path=str(new_root),
            allowed_capabilities=(ToolCapability.FILE_READ,),
            status=WorkspaceAccessStatus.ACTIVE,
            expected_revision=1,
        ),
    )
    assert policy.evaluate(request).reason.value == "workspace_changed"
    assert (old_root / "source.txt").read_text() == "old" and (new_root / "source.txt").read_text() == "new"


def test_permission_change_invalidates_authority_even_when_root_is_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "source.txt").write_text("safe")
    store = WorkspaceAccessStore()
    admin = WorkspaceAccessService(store, Admin())
    create(admin, "workspace", root)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="files.read",
            name="Read",
            description="Read file",
            tool_version="1",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            required_capabilities=(ToolCapability.FILE_READ,),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        )
    )
    features = ToolFeatureService(registry, ToolFeatureStore(), Admin())
    features.update(
        UpdateToolFeaturesRequest(framework_enabled=True, enabled_tool_ids=("files.read",), expected_version=0)
    )
    resolver = WorkspaceResolver(WorkspaceRegistry(), create_workspace_access_lookup(store))
    initial = resolver.resolve_tool_access("workspace")
    caps = frozenset({ToolCapability.FILE_READ})
    authority = Authority(
        ToolExecutionAuthority(
            context=ToolExecutionContext(
                context_id="ctx",
                workspace_id="workspace",
                workspace_authorization_ref="scope",
                tool_policy_ref="policy",
                caller_authority_ref="caller",
            ),
            workspace=bind_workspace(initial),
            revision_ref="rev-1",
            allowed_tool_ids=frozenset({"files.read"}),
            allowed_capabilities=caps,
            technical_capabilities=caps,
        )
    )
    policy = ToolPolicyService(
        registry, features, resolver, authority=authority, operations={"files.read": ToolOperationType.READ}
    )
    request = ToolPolicyRequest(
        request=ToolRequest(
            invocation_id="invoke",
            tool_id="files.read",
            tool_version="1",
            arguments={"path": "source.txt"},
            execution_context_ref="ctx",
        )
    )
    assert policy.evaluate(request).decision.value == "allow"
    admin.update(
        "workspace",
        UpdateWorkspaceAccessRequest(
            kind=WorkspaceKind.LOCAL,
            root_path=str(root),
            allowed_capabilities=(ToolCapability.FILE_READ,),
            status=WorkspaceAccessStatus.ACTIVE,
            expected_revision=1,
        ),
    )
    assert policy.evaluate(request).reason.value == "workspace_changed"
    assert (root / "source.txt").read_text() == "safe"


def test_workspace_capability_restrictions_are_a_ceiling_on_authority(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "source.txt").write_text("safe")
    store = WorkspaceAccessStore()
    create(WorkspaceAccessService(store, Admin()), "workspace", root)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="files.delete",
            name="Delete",
            description="Delete file",
            tool_version="1",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            required_capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        )
    )
    features = ToolFeatureService(registry, ToolFeatureStore(), Admin())
    features.update(
        UpdateToolFeaturesRequest(framework_enabled=True, enabled_tool_ids=("files.delete",), expected_version=0)
    )
    resolved = WorkspaceResolver(WorkspaceRegistry(), create_workspace_access_lookup(store)).resolve_tool_access(
        "workspace"
    )
    authority_capabilities = frozenset(
        {ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE}
    )
    authority = Authority(
        ToolExecutionAuthority(
            context=ToolExecutionContext(
                context_id="ctx",
                workspace_id="workspace",
                workspace_authorization_ref="scope",
                tool_policy_ref="policy",
                caller_authority_ref="caller",
            ),
            workspace=bind_workspace(resolved),
            revision_ref="rev-1",
            allowed_tool_ids=frozenset({"files.delete"}),
            allowed_capabilities=authority_capabilities,
            technical_capabilities=authority_capabilities,
        )
    )
    policy = ToolPolicyService(
        registry,
        features,
        WorkspaceResolver(WorkspaceRegistry(), create_workspace_access_lookup(store)),
        authority=authority,
        operations={"files.delete": ToolOperationType.DELETE},
    )
    result = policy.evaluate(
        ToolPolicyRequest(
            request=ToolRequest(
                invocation_id="invoke",
                tool_id="files.delete",
                tool_version="1",
                arguments={"path": "source.txt"},
                execution_context_ref="ctx",
            )
        )
    )
    assert result.reason.value == "capability_denied"
    assert (root / "source.txt").read_text() == "safe"


def test_root_retargeted_through_symlink_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    relocated = tmp_path / "relocated"
    root.mkdir()
    relocated.mkdir()
    store = WorkspaceAccessStore()
    create(WorkspaceAccessService(store, Admin()), "workspace", root)
    root.rename(tmp_path / "original-root")
    root.symlink_to(relocated, target_is_directory=True)
    assert create_workspace_access_lookup(store).resolve("workspace") == (True, None)


def test_default_administration_is_denied_and_root_not_disclosed(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    root.mkdir()
    store = WorkspaceAccessStore()
    create(WorkspaceAccessService(store, Admin()), "private", root)
    ordinary = WorkspaceAccessService(store, DeniedAdmin())
    assert not ordinary.state().can_manage and not ordinary.state().roots_disclosed
    assert ordinary.state().workspaces[0].root_path is None
    with pytest.raises(PermissionError):
        create(ordinary, "forbidden", root)
    request = cast(
        Request,
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(workspace_access_service=ordinary))),
    )
    response = create_workspace_access(
        request,
        CreateWorkspaceAccessRequest(
            workspace_id="api-forbidden", kind=WorkspaceKind.LOCAL, root_path=str(root)
        ),
    )
    assert isinstance(response, JSONResponse) and response.status_code == 403
    with pytest.raises(ValidationError):
        CreateWorkspaceAccessRequest.model_validate(
            {"workspace_id": "header-admin", "kind": "local", "root_path": str(root), "isAdmin": True}
        )


def test_overlapping_roots_remain_separate_registry_entries(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    nested = parent / "nested"
    nested.mkdir(parents=True)
    store = WorkspaceAccessStore()
    service = WorkspaceAccessService(store, Admin())
    create(service, "parent", parent)
    create(service, "nested", nested)
    lookup = create_workspace_access_lookup(store)
    parent_access, nested_access = lookup.resolve("parent")[1], lookup.resolve("nested")[1]
    assert parent_access is not None and parent_access.root_path == parent.resolve()
    assert nested_access is not None and nested_access.root_path == nested.resolve()
    assert WorkspaceRegistry().list() == []


def test_workspace_authority_requires_capability_and_registry_is_not_grant(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = WorkspaceAccessStore()
    service = WorkspaceAccessService(store, Admin())
    create(service, "workspace", root)
    resolver = WorkspaceResolver(WorkspaceRegistry(), create_workspace_access_lookup(store))
    resolved = resolver.resolve_tool_access("workspace")
    assert resolved.permissions.read and resolved.permissions.write
    assert WorkspaceRegistry().get("workspace") is None
    # Configuration governs which Workspace may be resolved; the authority
    # issuer is absent and this Workspace alone does not fabricate a grant.
    assert ToolExecutionAuthority.__dataclass_fields__["allowed_tool_ids"]
    assert service.state().workspaces[0].allowed_capabilities == (ToolCapability.FILE_READ, ToolCapability.FILE_WRITE)
