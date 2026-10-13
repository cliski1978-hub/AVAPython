"""Focused durable approval lifecycle and security tests."""

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ava.contracts.approvals import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalHumanAuthority,
    ApprovalReason,
    ApprovalRequest,
    ApprovalStatus,
)
from ava.contracts.responses import RunStatus
from ava.contracts.tool_features import ToolFeatureConfiguration, UpdateToolFeaturesRequest
from ava.contracts.tool_policy import ToolPolicyDecision, ToolPolicyDecisionType, ToolPolicyReason
from ava.contracts.tools import (
    ToolApprovalRequirement,
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolExecutionContext,
    ToolOperationBinding,
    ToolRequest,
    ToolRisk,
)
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.approval_repository import (
    CorruptApprovalRecordError,
    RelationalApprovalRepository,
)
from ava.repositories.approval_repository import ApprovalConflictError
from ava.services.approval_service import ApprovalExpiredError, ApprovalService, ApprovalUnavailableError
from ava.services.approval_store import ApprovalStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_feature_store import ToolFeatureStore
from ava.tools.authority import ToolExecutionAuthority
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import (
    ResolvedWorkspace,
    RuntimeWorkspaceBinding,
    WorkspaceInfo,
    WorkspaceKind,
    WorkspacePermissions,
)
from ava.workspaces.registry import WorkspaceRegistry
from ava.workspaces.resolver import WorkspaceResolver


class _Policy:
    def __init__(self) -> None:
        self.requires_approval = True
        self.policy_version = "tool-policy-v1"

    def evaluate(self, candidate: object) -> ToolPolicyDecision:
        request = candidate.request
        if not self.requires_approval:
            return ToolPolicyDecision(
                invocation_id=request.invocation_id,
                tool_id=request.tool_id,
                decision=ToolPolicyDecisionType.DENY,
                reason=ToolPolicyReason.FEATURE_DISABLED,
                explanation="disabled",
                policy_version=self.policy_version,
            )
        digest = hashlib.sha256(repr(sorted(request.arguments.items())).encode()).hexdigest()
        binding = ToolOperationBinding(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            tool_version=request.tool_version,
            execution_context_ref=request.execution_context_ref,
            operation_digest=digest,
            authority_revision_ref="authority-r1",
        )
        return ToolPolicyDecision(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            decision=ToolPolicyDecisionType.REQUIRES_APPROVAL,
            reason=ToolPolicyReason.APPROVAL_REQUIRED,
            explanation="approval required",
            approval_required=True,
            configuration_version=1,
            policy_version=self.policy_version,
            operation_binding=binding,
        )


class _Authority:
    def __init__(self, root: Path) -> None:
        self.context = ToolExecutionContext(
            context_id="ctx-1",
            workspace_id="ws-1",
            workspace_authorization_ref="workspace-auth-1",
            tool_policy_ref="policy-1",
            caller_authority_ref="caller-1",
        )
        self.workspace = RuntimeWorkspaceBinding(
            workspace_id="ws-1",
            kind=WorkspaceKind.LOCAL,
            local_path=root,
            permissions=WorkspacePermissions(read=True, write=True),
            configuration_revision=3,
        )
        self.revision_ref = "authority-r1"
        self.run_id = "run-1"
        self.allowed_tool_ids = frozenset({"file.write"})
        self.allowed_capabilities = frozenset({ToolCapability.FILE_READ, ToolCapability.FILE_WRITE})
        self.technical_capabilities = self.allowed_capabilities
        self.narrowing_tool_ids = None
        self.revoked = False

    def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
        return ToolExecutionAuthority(
            context=self.context,
            workspace=self.workspace,
            revision_ref=self.revision_ref,
            allowed_tool_ids=self.allowed_tool_ids,
            allowed_capabilities=self.allowed_capabilities,
            technical_capabilities=self.technical_capabilities,
            run_id=self.run_id,
            narrowing_tool_ids=self.narrowing_tool_ids,
            revoked=self.revoked,
        )


class _DecisionAuthority:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def resolve_for(self, approval: object) -> ApprovalHumanAuthority | None:
        if not self.allowed:
            return None
        return ApprovalHumanAuthority(
            principal_ref="human-1",
            authority_revision_ref="human-authority-1",
            workspace_ids=frozenset({"ws-1"}),
            can_decide=True,
        )


class _Fixture:
    def __init__(self, root: Path, repository: object | None = None, *, now: datetime | None = None) -> None:
        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                tool_id="file.write",
                name="Write file",
                description="Write a Workspace file",
                tool_version="1",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                required_capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE),
                risk=ToolRisk.HIGH,
                approval_requirement=ToolApprovalRequirement.REQUIRED,
                execution_category=ToolExecutionCategory.DETERMINISTIC,
            )
        )
        self.features_repository = ToolFeatureStore()
        self.features_repository.compare_and_set(
            0,
            ToolFeatureConfiguration(
                framework_enabled=True,
                enabled_tool_ids=("file.write",),
                configuration_version=1,
            ),
        )
        self.features = ToolFeatureService(self.registry, self.features_repository)
        resolved = ResolvedWorkspace(
            info=WorkspaceInfo("ws-1", "Test Workspace", WorkspaceKind.LOCAL),
            root_path=root,
            permissions=WorkspacePermissions(read=True, write=True),
            configuration_revision=3,
        )
        self.workspace_registry = WorkspaceRegistry()
        self.workspace_registry.register(resolved)
        self.workspaces = WorkspaceResolver(self.workspace_registry)
        self.authority = _Authority(root)
        self.policy = _Policy()
        self.runs = RunStore()
        self.runs.create("run-1")
        self.clock_value = now or datetime(2026, 1, 1, tzinfo=UTC)
        self.repository = repository or ApprovalStore()
        self.service = self.make_service()

    def make_service(self, *, decision_authority: object | None = None) -> ApprovalService:
        return ApprovalService(
            self.repository,
            self.runs,
            self.policy,
            self.features,
            self.workspaces,
            self.authority,
            self.registry,
            decision_authority=decision_authority or _DecisionAuthority(),
            now=lambda: self.clock_value,
        )

    def request(self, *, invocation_id: str = "inv-1", path: str = "notes.txt") -> ToolRequest:
        return ToolRequest(
            invocation_id=invocation_id,
            tool_id="file.write",
            tool_version="1",
            arguments={"path": path, "content": "hello"},
            execution_context_ref="ctx-1",
            run_id="run-1",
        )

    def create(self, request: ToolRequest | None = None):
        request = request or self.request()
        return self.service.request(ApprovalRequest(run_id="run-1", tool_request=request))


def test_create_rechecks_policy_and_rejects_denials_and_fabricated_decisions(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    request = fixture.request()
    created = fixture.create(request)
    assert created.status == ApprovalStatus.PENDING
    assert "content" not in created.model_dump_json()
    assert str(tmp_path) not in created.model_dump_json()

    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(
            {"run_id": "run-1", "tool_request": request.model_dump(), "policy_decision": "requires_approval"}
        )

    fixture.policy.requires_approval = False
    with pytest.raises(ApprovalUnavailableError, match="does not require approval"):
        fixture.create(fixture.request(invocation_id="inv-2"))


def test_duplicate_request_is_idempotent_only_for_same_pending_fingerprint(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    assert fixture.create() == record
    with pytest.raises(ApprovalConflictError):
        fixture.create(fixture.request(path="different.txt"))


def test_decision_requires_current_human_and_is_terminal_and_immutable(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    unauthorized = fixture.make_service(decision_authority=_DecisionAuthority(False))
    with pytest.raises(ApprovalUnavailableError, match="not found"):
        unauthorized.get_for_current_human(record.approval_id)
    with pytest.raises(ApprovalUnavailableError, match="human approval authority"):
        unauthorized.decide(record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request())

    approved = fixture.service.decide(
        record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request()
    )
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.decision_metadata is not None
    assert approved.decision_metadata.principal_ref == "human-1"
    assert (
        fixture.service.decide(
            record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request()
        )
        == approved
    )
    with pytest.raises(ApprovalConflictError):
        fixture.service.decide(record.approval_id, ApprovalDecision(decision="deny"), current_request=fixture.request())
    assert fixture.service.cancel_for_run("run-1") == []


def test_human_denial_is_a_durable_terminal_decision(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    denied = fixture.service.decide(
        record.approval_id,
        ApprovalDecision(decision="deny", reason="Not authorized"),
        current_request=fixture.request(),
    )
    assert denied.status == ApprovalStatus.DENIED
    assert denied.decision_metadata is not None
    assert denied.decision_metadata.decision == ApprovalDecisionValue.DENY
    assert fixture.service.remains_valid(record.approval_id, current_request=fixture.request()) is False


def test_exact_invocation_run_and_operation_context_are_required(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    with pytest.raises(ApprovalUnavailableError, match="different invocation"):
        fixture.service.decide(
            record.approval_id,
            ApprovalDecision(decision="approve"),
            current_request=fixture.request(path="changed.txt"),
        )
    assert fixture.repository.get(record.approval_id).status == ApprovalStatus.PENDING
    fixture.service._current_requests[record.invocation_id] = fixture.request(path="changed.txt")
    assert (
        fixture.service.remains_valid(record.approval_id, current_request=fixture.request(path="changed.txt")) is False
    )
    assert fixture.service.get_for_current_human(record.approval_id).status == ApprovalStatus.INVALIDATED


def test_expiration_denial_cancellation_and_run_cancellation(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    fixture.clock_value += timedelta(minutes=16)
    assert fixture.service.get_for_current_human(record.approval_id).status == ApprovalStatus.EXPIRED
    with pytest.raises(ApprovalExpiredError):
        fixture.service.decide(
            record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request()
        )

    fixture2 = _Fixture(tmp_path)
    cancelled = fixture2.create()
    assert fixture2.service.cancel_for_run("run-1")[0].status == ApprovalStatus.CANCELLED
    assert (
        fixture2.service.get_for_current_human(cancelled.approval_id).resolution_reason == ApprovalReason.RUN_CANCELLED
    )

    fixture3 = _Fixture(tmp_path)
    cancelled = fixture3.create()
    result = fixture3.service.cancel(cancelled.approval_id, current_request=fixture3.request())
    assert result.status == ApprovalStatus.CANCELLED
    assert result.resolution_reason == ApprovalReason.CANCELLED


def test_workspace_and_feature_changes_invalidate_pending_or_block_approved(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    pending = fixture.create()
    assert fixture.service.invalidate_workspace("ws-1")[0].status == ApprovalStatus.INVALIDATED
    assert (
        fixture.service.get_for_current_human(pending.approval_id).resolution_reason
        == ApprovalReason.WORKSPACE_REVOKED_OR_CHANGED
    )

    fixture2 = _Fixture(tmp_path)
    approved = fixture2.service.decide(
        fixture2.create().approval_id, ApprovalDecision(decision="approve"), current_request=fixture2.request()
    )
    fixture2.features_repository.compare_and_set(
        1,
        ToolFeatureConfiguration(framework_enabled=False, configuration_version=2),
    )
    assert fixture2.service.remains_valid(approved.approval_id, current_request=fixture2.request()) is False


def test_workspace_revision_authority_revocation_and_policy_revision_require_new_approval(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    fixture.workspace_registry._items["ws-1"] = ResolvedWorkspace(
        info=WorkspaceInfo("ws-1", "Test Workspace", WorkspaceKind.LOCAL),
        root_path=tmp_path / "changed-root",
        permissions=WorkspacePermissions(read=True, write=True),
        configuration_revision=4,
    )
    with pytest.raises(ApprovalUnavailableError, match="security context has changed"):
        fixture.service.decide(
            record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request()
        )

    fixture2 = _Fixture(tmp_path)
    revoked_record = fixture2.create()
    fixture2.authority.revoked = True
    with pytest.raises(ApprovalUnavailableError, match="Trusted execution authority"):
        fixture2.service.decide(
            revoked_record.approval_id,
            ApprovalDecision(decision="approve"),
            current_request=fixture2.request(),
        )

    fixture3 = _Fixture(tmp_path)
    policy_record = fixture3.create()
    fixture3.policy.policy_version = "tool-policy-v2"
    assert fixture3.service.remains_valid(policy_record.approval_id, current_request=fixture3.request()) is False


def test_run_cancellation_invalidates_pending_approval_eligibility(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    fixture.runs.request_cancellation("run-1", requested_at=fixture.clock_value)
    with pytest.raises(ApprovalUnavailableError, match="no longer eligible"):
        fixture.service.decide(
            record.approval_id, ApprovalDecision(decision="approve"), current_request=fixture.request()
        )
    assert fixture.service.get_for_current_human(record.approval_id).resolution_reason == ApprovalReason.RUN_CANCELLED


def test_run_service_cancellation_reconciles_pending_approvals(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    service = RunService(
        object(),
        run_repository=fixture.runs,
        run_event_repository=RunEventStore(),
        approval_cancellation=fixture.service.cancel_for_run,
    )
    result = asyncio.run(service.cancel_run("run-1"))
    assert result.status == RunStatus.CANCELLED
    assert fixture.repository.get(record.approval_id).resolution_reason == ApprovalReason.RUN_CANCELLED


def test_feature_gate_change_hook_invalidates_pending_records(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()

    class _Admin:
        def can_manage(self) -> bool:
            return True

    service = ToolFeatureService(
        fixture.registry,
        fixture.features_repository,
        _Admin(),
        on_configuration_changed=fixture.service.invalidate_all_pending,
    )
    service.update(
        UpdateToolFeaturesRequest(
            framework_enabled=False,
            enabled_tool_ids=(),
            expected_version=1,
        )
    )
    assert fixture.repository.get(record.approval_id).status == ApprovalStatus.INVALIDATED


def test_repository_compare_and_set_allows_only_one_terminal_resolution(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    record = fixture.create()
    approved = record.model_copy(
        update={"status": ApprovalStatus.CANCELLED, "resolution_reason": ApprovalReason.CANCELLED}
    )
    denied = record.model_copy(
        update={"status": ApprovalStatus.INVALIDATED, "resolution_reason": ApprovalReason.ELIGIBILITY_UNAVAILABLE}
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda replacement: fixture.repository.compare_and_set(
                    record.approval_id, ApprovalStatus.PENDING, replacement
                ),
                (approved, denied),
            )
        )
    assert sum(result is not None for result in results) == 1


def test_sqlite_repository_survives_restart_and_corruption_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "approvals.sqlite3"
    database = SqliteDatabase(str(database_path))
    repository = RelationalApprovalRepository(database)
    fixture = _Fixture(tmp_path, repository=repository)
    record = fixture.create()
    database.dispose()

    reopened = SqliteDatabase(str(database_path))
    reopened_repository = RelationalApprovalRepository(reopened)
    assert reopened_repository.get(record.approval_id) == record
    fixture.repository = reopened_repository
    restarted_service = fixture.make_service()
    assert restarted_service.list_pending_for_current_human() == []
    historical = restarted_service.get_for_current_human(record.approval_id)
    assert historical.status == ApprovalStatus.INVALIDATED
    assert historical.resolution_reason == ApprovalReason.ELIGIBILITY_UNAVAILABLE
    with reopened.transaction() as connection:
        connection.execute(
            "UPDATE approval_records SET record_json = '{broken' WHERE approval_id = ?", (record.approval_id,)
        )
    with pytest.raises(CorruptApprovalRecordError):
        reopened_repository.get(record.approval_id)
    reopened.dispose()


def test_approval_service_has_no_runtime_model_dispatch_or_filesystem_dependencies() -> None:
    import ast

    source = Path(__file__).parents[1] / "src" / "ava" / "services" / "approval_service.py"
    imports = {
        alias.name
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = (
        "ava.agents",
        "ava.execution",
        "ava.infrastructure",
        "ava.models",
        "ava.runtimes",
        "openhands",
        "openai",
        "anthropic",
        "os",
        "pathlib",
        "subprocess",
    )
    assert not any(name == prefix or name.startswith(prefix + ".") for name in imports for prefix in forbidden)
