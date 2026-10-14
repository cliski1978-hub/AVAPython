from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.api.principal import UnavailableHttpPrincipalResolver
from ava.contracts.execution import ExecutionMode
from ava.contracts.security_identity import (
    DenyConversationAccess,
    DenyPrincipalValidity,
    PrincipalActorType,
    PrincipalResolution,
    PrincipalResolutionStatus,
    VerifiedPrincipal,
)
from ava.contracts.tools import ToolCapability
from ava.contracts.workspace_access import WorkspaceAccessConfiguration, WorkspaceAccessStatus
from ava.contracts.workspace_grants import WorkspaceGrant, WorkspaceGrantStatus
from ava.infrastructure.composition import create_tool_registry, create_workspace_registry
from ava.infrastructure.persistence.composition import create_relational_repositories
from ava.infrastructure.workspace_access_lookup import PersistentWorkspaceAccessLookup
from ava.services.run_execution_authority_service import RunExecutionAuthorityService
from ava.services.workspace_access_store import WorkspaceAccessStore
from ava.services.workspace_grant_service import WorkspaceGrantService
from ava.services.workspace_grant_store import WorkspaceGrantStore
from ava.workspaces.resolver import WorkspaceResolver


def _principal(subject: str = "alice", tenant: str | None = "org-a") -> VerifiedPrincipal:
    now = datetime.now(UTC)
    return VerifiedPrincipal(
        identity_provider="https://issuer.example/tenant",
        subject=subject,
        tenant_ref=tenant,
        actor_type=PrincipalActorType.HUMAN,
        authentication_context="oidc_mfa",
        authentication_context_ref=sha256(f"test-session-{subject}".encode()).hexdigest(),
        authenticated_at=now,
        valid_until=now + timedelta(hours=1),
    )


class _PrincipalResolver:
    def __init__(self, principal: VerifiedPrincipal | None) -> None:
        self.principal = principal

    def resolve(self, request: object) -> PrincipalResolution:
        del request
        if self.principal is None:
            return PrincipalResolution(status=PrincipalResolutionStatus.UNAUTHENTICATED)
        return PrincipalResolution(status=PrincipalResolutionStatus.AUTHENTICATED, principal=self.principal)


class _Validity:
    def __init__(self, current: bool = True) -> None:
        self.current = current

    def is_current(self, principal_ref: str, authentication_context_ref: str) -> bool:
        del principal_ref, authentication_context_ref
        return self.current


def _trusted_app(principal: VerifiedPrincipal | None = None, *, current: bool = True):
    return create_app(
        http_principal_resolver=_PrincipalResolver(principal or _principal()),
        principal_validity=_Validity(current),
        conversation_access=DenyConversationAccess(),
    )


def test_unconfigured_authentication_fails_closed_and_spoofed_roles_do_not_authenticate() -> None:
    client = TestClient(
        create_app(
            http_principal_resolver=UnavailableHttpPrincipalResolver(),
            principal_validity=DenyPrincipalValidity(),
        )
    )
    response = client.get("/runs/missing", headers={"X-AVA-Role": "admin", "X-AVA-Principal": "alice"})
    assert response.status_code == 503

    app = create_app(http_principal_resolver=_PrincipalResolver(None), principal_validity=_Validity())
    assert TestClient(app).get("/runs/missing").status_code == 401
    assert _trusted_app().state.run_access_service is not None


def test_linked_run_context_is_unavailable_until_conversation_ownership_exists() -> None:
    client = TestClient(_trusted_app())
    body = {"prompt": "linked", "conversation_id": str(uuid4())}
    assert client.post("/runs", json=body).status_code == 503
    assert client.post("/runs/context-preview", json=body).status_code == 503


def test_authenticated_workspace_grant_mutations_remain_default_denied() -> None:
    client = TestClient(_trusted_app())
    workspace_run = client.post("/runs", json={"prompt": "workspace scoped", "workspace_id": "private"})
    assert workspace_run.status_code == 503
    preview = client.post(
        "/runs/context-preview", json={"prompt": "workspace scoped", "workspace_id": "private"}
    )
    assert preview.status_code == 503
    response = client.post(
        "/settings/workspace-access/private/grants",
        json={
            "principal_ref": _principal().principal_ref,
            "tenant_ref": "org-a",
            "capabilities": ["file_read"],
            "expected_workspace_revision": 1,
        },
    )
    assert response.status_code == 403


def test_verified_principal_rejects_provider_userinfo_and_secret_shaped_context() -> None:
    with pytest.raises(ValueError):
        VerifiedPrincipal(
            identity_provider="https://user:password@issuer.example",
            subject="alice",
            actor_type=PrincipalActorType.HUMAN,
            authentication_context="mfa",
            authentication_context_ref="a" * 64,
            authenticated_at=datetime.now(UTC),
        )
    with pytest.raises(ValueError):
        VerifiedPrincipal(
            identity_provider="https://issuer.example",
            subject="alice",
            actor_type=PrincipalActorType.HUMAN,
            authentication_context="bearer-token-value",
            authentication_context_ref="a" * 64,
            authenticated_at=datetime.now(UTC),
        )


def test_verified_principal_rejects_raw_authentication_context_reference() -> None:
    with pytest.raises(ValueError):
        VerifiedPrincipal(
            identity_provider="https://issuer.example",
            subject="alice",
            actor_type=PrincipalActorType.HUMAN,
            authentication_context="oidc_mfa",
            authentication_context_ref="session-token-value-that-must-not-be-persisted",
            authenticated_at=datetime.now(UTC),
        )


def test_run_routes_hide_foreign_and_ownerless_records_and_bind_new_run_to_resolved_principal() -> None:
    app = _trusted_app()
    client = TestClient(app)
    created = client.post("/runs", json={"prompt": "standalone run"})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    stored = app.state.persistence.run_repository.get(run_id)
    assert stored is not None
    assert stored.owner_principal_ref == _principal().principal_ref
    assert stored.owner_tenant_ref == "org-a"
    assert stored.owner_auth_context_ref == _principal().authentication_context_ref

    assert client.get(f"/runs/{run_id}").status_code == 200
    assert client.get(f"/runs/{run_id}/events").status_code == 200
    assert client.get(f"/runs/{run_id}/inspection").status_code == 200

    conversation = app.state.conversation_service.create_conversation()
    assert client.get(f"/runs?conversation_id={conversation.conversation_id}").status_code == 503
    app.state.conversation_access = SimpleNamespace(can_access=lambda *args: True)
    app.state.run_lifecycle_service.create_run(
        "owned-list-entry",
        conversation_id=conversation.conversation_id,
        execution_mode=ExecutionMode.AGENT,
        owner_principal_ref=_principal().principal_ref,
        owner_tenant_ref="org-a",
        owner_auth_context_ref=_principal().authentication_context_ref,
    )
    app.state.run_lifecycle_service.start("owned-list-entry")
    app.state.run_lifecycle_service.complete("owned-list-entry")
    app.state.run_lifecycle_service.create_run(
        "foreign-list-entry",
        conversation_id=conversation.conversation_id,
        execution_mode=ExecutionMode.AGENT,
        owner_principal_ref=_principal("bob").principal_ref,
        owner_tenant_ref="org-a",
        owner_auth_context_ref=_principal("bob").authentication_context_ref,
    )
    app.state.run_lifecycle_service.start("foreign-list-entry")
    app.state.run_lifecycle_service.complete("foreign-list-entry")
    app.state.run_lifecycle_service.create_run(
        "ownerless-list-entry", conversation_id=conversation.conversation_id, execution_mode=ExecutionMode.AGENT
    )
    app.state.run_lifecycle_service.start("ownerless-list-entry")
    app.state.run_lifecycle_service.complete("ownerless-list-entry")
    listed = client.get(f"/runs?conversation_id={conversation.conversation_id}")
    assert listed.status_code == 200
    assert [item["run_id"] for item in listed.json()] == ["owned-list-entry"]

    app.state.http_principal_resolver = _PrincipalResolver(_principal("bob", "org-a"))
    assert client.get(f"/runs/{run_id}").status_code == 404
    listed_as_bob = client.get(f"/runs?conversation_id={conversation.conversation_id}")
    assert [item["run_id"] for item in listed_as_bob.json()] == ["foreign-list-entry"]
    assert client.get(f"/runs/{run_id}/events").status_code == 404
    assert client.get(f"/runs/{run_id}/inspection").status_code == 404
    assert client.post(f"/runs/{run_id}/cancel").status_code == 404

    app.state.http_principal_resolver = _PrincipalResolver(_principal())
    app.state.run_lifecycle_service.create_run("legacy-ownerless")
    assert client.get("/runs/legacy-ownerless").status_code == 404


def test_expired_or_revoked_authentication_context_is_rejected() -> None:
    app = _trusted_app(current=False)
    assert TestClient(app).get("/runs/not-visible").status_code == 401


def test_cross_tenant_run_access_is_denied_even_for_the_same_subject() -> None:
    app = _trusted_app(_principal(tenant="org-a"))
    client = TestClient(app)
    response = client.post("/runs", json={"prompt": "tenant scoped"})
    run_id = response.json()["run_id"]
    app.state.http_principal_resolver = _PrincipalResolver(_principal(tenant="org-b"))
    assert client.get(f"/runs/{run_id}").status_code == 404


class _GrantAdmin:
    def can_manage(self, principal: VerifiedPrincipal, *, workspace_id: str, action: str) -> bool:
        del principal, workspace_id, action
        return True


def test_workspace_grants_are_admin_assigned_revisioned_and_terminal_when_revoked(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    workspaces = WorkspaceAccessStore()
    workspaces.create(
        WorkspaceAccessConfiguration(
            workspace_id="personal",
            name="Personal",
            kind="local",
            root_path=str(tmp_path.resolve()),
            allowed_capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE),
            status=WorkspaceAccessStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    grants = WorkspaceGrantStore()
    service = WorkspaceGrantService(grants=grants, workspaces=workspaces, administration=_GrantAdmin())
    alice = _principal()
    from ava.contracts.workspace_grants import CreateWorkspaceGrantRequest, UpdateWorkspaceGrantRequest

    item = service.create(
        alice,
        "personal",
        CreateWorkspaceGrantRequest(
            principal_ref=alice.principal_ref,
            tenant_ref="org-a",
            capabilities=(ToolCapability.FILE_READ,),
            expected_workspace_revision=1,
        ),
    )
    assert item.revision == 1 and item.capabilities == (ToolCapability.FILE_READ,)
    user_service = WorkspaceGrantService(grants=grants, workspaces=workspaces)
    with pytest.raises(PermissionError):
        user_service.update(
            alice,
            item.grant_id,
            UpdateWorkspaceGrantRequest(
                capabilities=(ToolCapability.FILE_WRITE,), expected_revision=1
            ),
        )
    widened = service.update(
        alice,
        item.grant_id,
        UpdateWorkspaceGrantRequest(capabilities=(ToolCapability.FILE_WRITE,), expected_revision=1),
    )
    assert widened.capabilities == (ToolCapability.FILE_WRITE,)
    revoked = service.update(
        alice,
        item.grant_id,
        UpdateWorkspaceGrantRequest(capabilities=(), expected_revision=2),
        revoke=True,
    )
    assert revoked.status == WorkspaceGrantStatus.REVOKED and revoked.revision == 3
    with pytest.raises(ValueError, match="cannot be updated or reactivated"):
        service.update(
            alice,
            item.grant_id,
            UpdateWorkspaceGrantRequest(capabilities=(ToolCapability.FILE_READ,), expected_revision=3),
        )


def test_authority_issuer_requires_owner_session_current_grant_and_matching_workspace(tmp_path: Path) -> None:
    alice = _principal()
    app = _trusted_app(alice)
    persistence = app.state.persistence
    now = datetime.now(UTC)
    workspace_id = "private"
    persistence.workspace_access_repository.create(
        WorkspaceAccessConfiguration(
            workspace_id=workspace_id,
            name="Private",
            kind="local",
            root_path=str(tmp_path.resolve()),
            allowed_capabilities=(ToolCapability.FILE_READ,),
            status=WorkspaceAccessStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    persistence.run_repository.create(
        "owned-agent-run",
        execution_mode=ExecutionMode.AGENT,
        owner_principal_ref=alice.principal_ref,
        owner_tenant_ref=alice.tenant_ref,
        owner_auth_context_ref=alice.authentication_context_ref,
        owner_auth_valid_until=alice.valid_until,
        execution_workspace_id=workspace_id,
    )
    features = SimpleNamespace(
        state=lambda: SimpleNamespace(
            configuration_status="valid",
            framework_effective_enabled=True,
            configuration=SimpleNamespace(configuration_version=1),
            tools=[],
        )
    )
    registry = create_tool_registry()
    resolver = WorkspaceResolver(
        create_workspace_registry(), PersistentWorkspaceAccessLookup(persistence.workspace_access_repository)
    )
    issuer = RunExecutionAuthorityService(
        runs=persistence.run_repository,
        workspaces=resolver,
        workspace_configurations=persistence.workspace_access_repository,
        grants=persistence.workspace_grant_repository,
        features=features,
        registry=registry,
        policy=app.state.tool_policy_service,
        principal_validity=_Validity(),
    )
    assert issuer.resolve_context(run_id="owned-agent-run", workspace_id="wrong") is None
    handle = issuer.resolve_context(run_id="owned-agent-run", workspace_id=workspace_id)
    assert handle is not None
    assert issuer.resolve(handle) is None
    grant = WorkspaceGrant(
        grant_id="a" * 32,
        workspace_id=workspace_id,
        principal_ref=alice.principal_ref,
        tenant_ref=alice.tenant_ref,
        capabilities=(ToolCapability.FILE_READ,),
        workspace_configuration_revision=1,
        status=WorkspaceGrantStatus.ACTIVE,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    persistence.workspace_grant_repository.create(grant)
    assert issuer.resolve(handle) is not None
    persistence.workspace_grant_repository.compare_and_set(
        1, grant.model_copy(update={"status": WorkspaceGrantStatus.REVOKED, "revision": 2, "updated_at": now})
    )
    assert issuer.resolve(handle) is None


def test_run_ownership_round_trips_through_sqlite(tmp_path: Path) -> None:
    principal = _principal()
    repositories = create_relational_repositories(str(tmp_path / "ownership.sqlite3"))
    try:
        now = datetime.now(UTC)
        repositories.workspace_access_repository.create(
            WorkspaceAccessConfiguration(
                workspace_id="private",
                name="Private",
                kind="local",
                root_path=str(tmp_path.resolve()),
                allowed_capabilities=(ToolCapability.FILE_READ,),
                status=WorkspaceAccessStatus.ACTIVE,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )
        created = repositories.run_repository.create(
            "durable-owned-run",
            execution_mode=ExecutionMode.AGENT,
            owner_principal_ref=principal.principal_ref,
            owner_tenant_ref=principal.tenant_ref,
            owner_auth_context_ref=principal.authentication_context_ref,
            owner_auth_valid_until=principal.valid_until,
            execution_workspace_id="private",
        )
        assert created.owner_principal_ref == principal.principal_ref
        loaded = repositories.run_repository.get("durable-owned-run")
        assert loaded is not None
        assert loaded.owner_principal_ref == principal.principal_ref
        assert loaded.owner_tenant_ref == "org-a"
        assert loaded.owner_auth_context_ref == principal.authentication_context_ref
        assert loaded.execution_workspace_id == "private"
        assert loaded.owner_auth_valid_until == principal.valid_until
        grant = WorkspaceGrant(
            grant_id="b" * 32,
            workspace_id="private",
            principal_ref=principal.principal_ref,
            tenant_ref=principal.tenant_ref,
            capabilities=(ToolCapability.FILE_READ,),
            workspace_configuration_revision=1,
            status=WorkspaceGrantStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        repositories.workspace_grant_repository.create(grant)
        stored_grant = repositories.workspace_grant_repository.get(grant.grant_id)
        assert stored_grant == grant
    finally:
        repositories.dispose()
