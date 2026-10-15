from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from test_approvals import _Fixture

from ava.api.app import create_app
from ava.contracts.approvals import ApprovalDecision, ApprovalStatus
from ava.contracts.security_identity import (
    PrincipalActorType,
    PrincipalResolution,
    PrincipalResolutionStatus,
    VerifiedPrincipal,
)
from ava.infrastructure.workspace_admin_policy import (
    ConfiguredWorkspaceGrantAdministration,
    WorkspaceAdminApprovalDecisionAuthority,
)
from ava.services.approval_service import ApprovalUnavailableError
from ava.services.conversation_access_service import RepositoryConversationAccess


def _principal(subject: str, tenant: str = "tenant-a") -> VerifiedPrincipal:
    now = datetime.now(UTC)
    return VerifiedPrincipal(
        identity_provider="https://issuer.example",
        subject=subject,
        tenant_ref=tenant,
        actor_type=PrincipalActorType.HUMAN,
        authentication_context="oidc_mfa",
        authentication_context_ref=sha256(f"session-{subject}".encode()).hexdigest(),
        authenticated_at=now,
        valid_until=now + timedelta(hours=1),
    )


class _Resolver:
    def __init__(self, principal: VerifiedPrincipal) -> None:
        self.principal = principal

    def resolve(self, request: object) -> PrincipalResolution:
        del request
        return PrincipalResolution(status=PrincipalResolutionStatus.AUTHENTICATED, principal=self.principal)


class _Validity:
    def is_current(self, principal_ref: str, authentication_context_ref: str) -> bool:
        del principal_ref, authentication_context_ref
        return True


def _app(principal: VerifiedPrincipal):
    app = create_app(http_principal_resolver=_Resolver(principal), principal_validity=_Validity())
    app.state.conversation_access = RepositoryConversationAccess(app.state.persistence.conversation_repository)
    return app


@pytest.mark.asyncio
async def test_conversation_ownership_is_durable_and_scoped_by_principal_and_tenant() -> None:
    alice = _principal("alice")
    app = _app(alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/conversations", json={"title": "private"})
        assert created.status_code == 201
        conversation_id = created.json()["conversation_id"]
        assert [item["conversation_id"] for item in (await client.get("/conversations")).json()["conversations"]] == [
            conversation_id
        ]
        persisted = app.state.persistence.conversation_repository.get(conversation_id)
        assert persisted.owner_principal_ref == alice.principal_ref
        assert persisted.owner_tenant_ref == "tenant-a"

        app.state.http_principal_resolver = _Resolver(_principal("bob"))
        assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404
        assert (await client.get("/conversations")).json()["conversations"] == []

        app.state.http_principal_resolver = _Resolver(_principal("alice", tenant="tenant-b"))
        assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404


@pytest.mark.asyncio
async def test_conversation_folder_ownership_and_core_prompt_resolution_are_scoped() -> None:
    alice = _principal("alice")
    app = _app(alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        folder = await client.post("/conversation-folders", json={"name": "Private"})
        assert folder.status_code == 201
        folder_id = folder.json()["id"]
        conversation = await client.post("/conversations", json={"folder_id": folder_id})
        assert conversation.status_code == 201
        conversation_id = conversation.json()["conversation_id"]

        app.state.http_principal_resolver = _Resolver(_principal("bob"))
        assert (await client.get("/conversation-folders")).json()["folders"] == []
        assert (await client.get(f"/conversation-folders/{folder_id}")).status_code == 404
        assert (await client.patch(f"/conversation-folders/{folder_id}", json={"name": "Stolen"})).status_code == 404
        assert (await client.delete(f"/conversation-folders/{folder_id}")).status_code == 404
        assert (
            await client.post("/core-prompts/resolve", json={"conversation_id": conversation_id})
        ).status_code == 404
        assert (await client.post("/conversations", json={"folder_id": folder_id})).status_code == 404


@pytest.mark.asyncio
async def test_project_cascade_delete_cannot_remove_another_owners_conversations() -> None:
    alice = _principal("alice")
    app = _app(alice)
    project = app.state.project_service.create_project(
        name="Alice project", owner_principal_ref=alice.principal_ref, owner_tenant_ref=alice.tenant_ref
    )
    conversation = app.state.conversation_service.create_conversation_in_project(
        project.id, title="Alice's conversation", owner_principal_ref=alice.principal_ref,
        owner_tenant_ref=alice.tenant_ref,
    )
    app.state.http_principal_resolver = _Resolver(_principal("bob"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ordinary_delete = await client.delete(f"/projects/{project.id}")
        assert ordinary_delete.status_code == 404
        response = await client.delete(f"/projects/{project.id}?delete_conversations=true")
    assert response.status_code == 404
    assert app.state.persistence.conversation_repository.get(conversation.conversation_id) is not None
    assert app.state.project_service.get_project(project.id) is not None


@pytest.mark.asyncio
async def test_project_reads_and_files_are_owner_scoped() -> None:
    alice = _principal("alice")
    app = _app(alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/projects", json={"name": "Private", "instructions": "secret"})
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert [item["id"] for item in (await client.get("/projects")).json()["projects"]] == [project_id]

        app.state.http_principal_resolver = _Resolver(_principal("bob"))
        assert (await client.get("/projects")).json()["projects"] == []
        assert (await client.get(f"/projects/{project_id}")).status_code == 404
        assert (await client.get(f"/projects/{project_id}/files")).status_code == 404
        assert (await client.patch(f"/projects/{project_id}", json={"name": "Stolen"})).status_code == 404


@pytest.mark.asyncio
async def test_global_core_prompt_mutations_require_configured_administrator(monkeypatch) -> None:
    alice = _principal("alice")
    app = _app(alice)
    payload = {"name": "Owner managed", "prompt_text": "Safe prompt", "category": "core"}
    monkeypatch.delenv("AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/core-prompts", json=payload)
        assert denied.status_code == 403
        monkeypatch.setenv("AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS", alice.principal_ref)
        created = await client.post("/core-prompts", json=payload)
        assert created.status_code == 201
        prompt_id = created.json()["id"]
        monkeypatch.delenv("AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS", raising=False)
        assert (await client.get(f"/core-prompts/{prompt_id}/assignments")).status_code == 403
        assert (
            await client.get(
                "/core-prompt-assignments", params={"scope_type": "conversation", "scope_id": "private-id"}
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_approval_review_api_rejects_untrusted_identity_and_redacts_operation_fields(
    monkeypatch, tmp_path
) -> None:
    alice = _principal("alice")
    app = _app(alice)
    fixture = _Fixture(Path(tmp_path))
    monkeypatch.setenv(
        "AVA_WORKSPACE_GRANT_ADMIN_POLICY",
        json.dumps([{"workspace_id": "ws-1", "tenant_ref": "tenant-a", "principal_refs": [alice.principal_ref]}]),
    )
    fixture.service = fixture.make_service(
        decision_authority=WorkspaceAdminApprovalDecisionAuthority(
            ConfiguredWorkspaceGrantAdministration.from_environment()
        )
    )
    record = fixture.create()
    app.state.approval_service = fixture.service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        review = await client.get(f"/approvals/{record.approval_id}")
        assert review.status_code == 200
        assert "operation_binding" not in review.text
        assert "arguments" not in review.text
        forged = await client.post(
            f"/approvals/{record.approval_id}/decision",
            json={"decision": "approve", "principal_ref": alice.principal_ref},
        )
        assert forged.status_code == 422
        decision = await client.post(
            f"/approvals/{record.approval_id}/decision", json=ApprovalDecision(decision="approve").model_dump()
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"
        assert (await client.get("/approvals")).json()["history"][0]["status"] == "approved"


def test_workspace_admin_authority_is_explicit_human_tenant_and_workspace_scoped(monkeypatch) -> None:
    alice = _principal("alice")
    monkeypatch.setenv(
        "AVA_WORKSPACE_GRANT_ADMIN_POLICY",
        json.dumps(
            [{"workspace_id": "workspace-a", "tenant_ref": "tenant-a", "principal_refs": [alice.principal_ref]}]
        ),
    )
    policy = ConfiguredWorkspaceGrantAdministration.from_environment()
    assert policy.can_manage(alice, workspace_id="workspace-a", action="approve")
    assert not policy.can_manage(alice, workspace_id="workspace-b", action="approve")
    assert not policy.can_manage(_principal("alice", tenant="tenant-b"), workspace_id="workspace-a", action="approve")


def test_approval_decision_is_bound_to_verified_principal_and_audited_atomically(monkeypatch, tmp_path) -> None:
    alice = _principal("alice")
    monkeypatch.setenv(
        "AVA_WORKSPACE_GRANT_ADMIN_POLICY",
        json.dumps([{"workspace_id": "ws-1", "tenant_ref": "tenant-a", "principal_refs": [alice.principal_ref]}]),
    )
    administration = ConfiguredWorkspaceGrantAdministration.from_environment()
    fixture = _Fixture(tmp_path)
    fixture.service = fixture.make_service(
        decision_authority=WorkspaceAdminApprovalDecisionAuthority(administration)
    )
    approval = fixture.create()

    with pytest.raises(ApprovalUnavailableError, match="not found"):
        fixture.service.get_for_current_human(approval.approval_id, principal=_principal("bob"))

    resolved = fixture.service.decide_for_current_human(
        approval.approval_id, ApprovalDecision(decision="approve"), principal=alice
    )
    assert resolved.status == ApprovalStatus.APPROVED
    events = fixture.repository.list_audit_events(approval.approval_id)
    assert [event.event_type.value for event in events] == ["requested", "approved"]
    assert events[1].actor_principal_ref == alice.principal_ref
