"""Durable approval lifecycle; no tool, model, or runtime execution."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ava.contracts.approvals import (
    ApprovalDecision,
    ApprovalDecisionAuthorityPort,
    ApprovalDecisionMetadata,
    ApprovalDecisionValue,
    ApprovalHumanAuthority,
    ApprovalInvocationResolverPort,
    ApprovalReason,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
    DenyApprovalDecisionAuthority,
)
from ava.contracts.responses import RunStatus
from ava.contracts.security_identity import PrincipalActorType, VerifiedPrincipal
from ava.contracts.tool_policy import ToolPolicyDecision, ToolPolicyDecisionType, ToolPolicyRequest
from ava.contracts.tools import ToolOperationBinding, ToolRequest
from ava.repositories.approval_repository import ApprovalConflictError, ApprovalRepository
from ava.repositories.run_repository import RunRepository
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_policy_service import ToolPolicyService
from ava.tools.authority import ToolExecutionAuthority, ToolExecutionAuthorityPort
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import ResolvedWorkspace
from ava.workspaces.resolver import WorkspaceResolver


@dataclass(frozen=True)
class _ApprovalEvaluation:
    decision: ToolPolicyDecision
    binding: ToolOperationBinding | None = None
    authority: ToolExecutionAuthority | None = None
    workspace: ResolvedWorkspace | None = None


class ApprovalUnavailableError(PermissionError):
    """The operation lacks current approval eligibility or human authority."""


class ApprovalExpiredError(ApprovalUnavailableError):
    """An approval expired before the requested decision."""


class ApprovalService:
    def __init__(
        self,
        repository: ApprovalRepository,
        runs: RunRepository,
        policy: ToolPolicyService,
        features: ToolFeatureService,
        workspaces: WorkspaceResolver,
        execution_authority: ToolExecutionAuthorityPort | None,
        registry: ToolRegistry,
        *,
        decision_authority: ApprovalDecisionAuthorityPort | None = None,
        invocation_resolver: ApprovalInvocationResolverPort | None = None,
        ttl: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("approval lifetime must be positive")
        self._repository = repository
        self._runs = runs
        self._policy = policy
        self._features = features
        self._workspaces = workspaces
        self._execution_authority = execution_authority
        self._registry = registry
        self._decision_authority = decision_authority or DenyApprovalDecisionAuthority()
        self._invocation_resolver = invocation_resolver
        self._current_requests: dict[str, ToolRequest] = {}
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))

    def request(self, candidate: ApprovalRequest) -> ApprovalRecord:
        """Re-evaluate current policy; a supplied decision is never accepted."""
        request = ApprovalRequest.model_validate(candidate.model_dump())
        invocation = request.tool_request
        if invocation.run_id != request.run_id:
            raise ApprovalUnavailableError("Approval request does not match its run.")
        existing = self._repository.get_by_invocation(invocation.invocation_id)
        if existing is not None:
            if existing.status == ApprovalStatus.PENDING:
                run = self._runs.get(request.run_id)
                current = self._evaluate(invocation, request.run_id)
                if (
                    run is not None
                    and not run.status.is_terminal
                    and not run.cancellation_requested
                    and current.decision.decision == ToolPolicyDecisionType.REQUIRES_APPROVAL
                    and current.binding == existing.operation_binding
                ):
                    self._current_requests[invocation.invocation_id] = invocation
                    return self._expire_if_due(existing)
            raise ApprovalConflictError("An approval already exists for this invocation.")
        run = self._runs.get(request.run_id)
        if run is None or run.status.is_terminal or run.cancellation_requested:
            raise ApprovalUnavailableError("The run is not eligible for an approval request.")
        context = self._evaluate(invocation, request.run_id)
        decision = context.decision
        if decision.decision != ToolPolicyDecisionType.REQUIRES_APPROVAL:
            raise ApprovalUnavailableError("Current policy does not require approval.")
        now = self._clock()
        definition = self._registry.get(invocation.tool_id)
        if definition is None:
            raise ApprovalUnavailableError("The tool is no longer registered.")
        authority = context.authority
        workspace = context.workspace
        if authority is None or workspace is None or context.binding is None:
            raise ApprovalUnavailableError("Trusted operation context is unavailable.")
        workspace_id = authority.context.workspace_id
        workspace_authorization_ref = authority.context.workspace_authorization_ref
        if workspace_id is None or workspace_authorization_ref is None:
            raise ApprovalUnavailableError("Workspace authority is unavailable.")
        record = ApprovalRecord(
            approval_id=f"approval:{uuid4().hex}",
            run_id=request.run_id,
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            tool_version=invocation.tool_version,
            operation_binding=context.binding,
            status=ApprovalStatus.PENDING,
            requested_at=now,
            expires_at=now + self._ttl,
            summary=f"{definition.name}: human approval required",
            policy_version=decision.policy_version,
            feature_configuration_version=decision.configuration_version or 0,
            workspace_id=workspace_id,
            workspace_authorization_ref=workspace_authorization_ref,
            workspace_configuration_revision=workspace.configuration_revision,
            authority_revision_ref=authority.revision_ref,
        )
        try:
            created = self._repository.create(record)
            self._current_requests[invocation.invocation_id] = invocation
            return created
        except ApprovalConflictError:
            # Concurrent retries are idempotent only for the exact same pending operation.
            winner = self._repository.get_by_invocation(invocation.invocation_id)
            if (
                winner is not None
                and winner.status == ApprovalStatus.PENDING
                and winner.operation_binding == record.operation_binding
            ):
                self._current_requests[invocation.invocation_id] = invocation
                return winner
            raise

    def get_for_current_human(
        self, approval_id: str, *, principal: VerifiedPrincipal | None = None
    ) -> ApprovalRecord:
        record = self._repository.get(approval_id)
        if record is None:
            raise ApprovalUnavailableError("Approval was not found.")
        try:
            self._resolve_human_authority(record, principal)
        except ApprovalUnavailableError as exc:
            raise ApprovalUnavailableError("Approval was not found.") from exc
        if record.status == ApprovalStatus.PENDING:
            self._revalidate_pending(record)
            record = self._repository.get(approval_id) or record
        return self._expire_if_due(record)

    def list_pending_for_current_human(
        self, *, limit: int = 100, principal: VerifiedPrincipal | None = None
    ) -> list[ApprovalRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("approval listing limit must be between 1 and 500")
        visible = []
        for record in self._repository.list_pending(limit=limit):
            try:
                self._resolve_human_authority(record, principal)
            except ApprovalUnavailableError:
                continue
            self._revalidate_pending(record)
            current_record = self._repository.get(record.approval_id) or record
            current = self._expire_if_due(current_record)
            if current.status == ApprovalStatus.PENDING:
                visible.append(current)
        return visible

    def list_for_current_human(
        self, *, limit: int = 100, principal: VerifiedPrincipal
    ) -> list[ApprovalRecord]:
        """Return pending and historical records only within current human scope."""
        visible: list[ApprovalRecord] = []
        for record in self._repository.list_recent(limit=limit):
            try:
                self._resolve_human_authority(record, principal)
            except ApprovalUnavailableError:
                continue
            if record.status == ApprovalStatus.PENDING:
                self._revalidate_pending(record)
                current = self._repository.get(record.approval_id) or record
                current = self._expire_if_due(current)
                if current.status != ApprovalStatus.PENDING:
                    try:
                        self._resolve_human_authority(current, principal)
                    except ApprovalUnavailableError:
                        continue
                visible.append(current)
            else:
                visible.append(record)
        return visible

    def decide_for_current_human(
        self, approval_id: str, decision: ApprovalDecision, *, principal: VerifiedPrincipal
    ) -> ApprovalRecord:
        """Resolve the current server-owned invocation; never accept it from HTTP."""
        record = self._repository.get(approval_id)
        if record is None:
            raise ApprovalUnavailableError("Approval was not found.")
        trusted_request = self._current_request(record)
        if trusted_request is None:
            self._resolve_human_authority(record, principal)
            if record.status == ApprovalStatus.PENDING:
                self._invalidate_pending(record, ApprovalReason.ELIGIBILITY_UNAVAILABLE)
            raise ApprovalUnavailableError("Current invocation eligibility cannot be re-established.")
        return self.decide(approval_id, decision, current_request=trusted_request, principal=principal)

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        current_request: ToolRequest,
        principal: VerifiedPrincipal | None = None,
    ) -> ApprovalRecord:
        decision = ApprovalDecision.model_validate(decision.model_dump())
        record = self._repository.get(approval_id)
        if record is None:
            raise ApprovalUnavailableError("Approval was not found.")
        record = self._expire_if_due(record)
        if record.status == ApprovalStatus.EXPIRED:
            raise ApprovalExpiredError("Approval has expired.")
        self._resolve_human_authority(record, principal)
        if record.status != ApprovalStatus.PENDING:
            return self._repeat_or_conflict(record, decision.decision)
        trusted_request = self._current_request(record)
        if trusted_request is None:
            self._invalidate_pending(record, ApprovalReason.ELIGIBILITY_UNAVAILABLE)
            raise ApprovalUnavailableError("Current invocation eligibility cannot be re-established.")
        if current_request != trusted_request:
            raise ApprovalUnavailableError("Approval is bound to a different invocation.")
        try:
            self._require_current_operation(record, trusted_request)
        except ApprovalUnavailableError:
            self._invalidate_pending(record, self._ineligibility_reason(record))
            raise
        authority = self._resolve_human_authority(record, principal)
        now = self._clock()
        metadata = ApprovalDecisionMetadata(
            decision=decision.decision,
            principal_ref=authority.principal_ref,
            authority_revision_ref=authority.authority_revision_ref,
            decided_at=now,
            reason=decision.reason,
        )
        status = (
            ApprovalStatus.APPROVED if decision.decision == ApprovalDecisionValue.APPROVE else ApprovalStatus.DENIED
        )
        replacement = record.model_copy(
            update={"status": status, "decision_metadata": metadata, "resolution_reason": None}
        )
        return self._resolve_pending(record, replacement)

    def cancel(self, approval_id: str, *, current_request: ToolRequest) -> ApprovalRecord:
        record = self._repository.get(approval_id)
        if record is None:
            raise ApprovalUnavailableError("Approval was not found.")
        record = self._expire_if_due(record)
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalUnavailableError("Only a pending approval can be cancelled.")
        trusted_request = self._current_request(record)
        if trusted_request is None or current_request != trusted_request:
            raise ApprovalUnavailableError("Current invocation eligibility cannot be re-established.")
        self._require_current_operation(record, trusted_request)
        self._resolve_human_authority(record)
        replacement = record.model_copy(
            update={"status": ApprovalStatus.CANCELLED, "resolution_reason": ApprovalReason.CANCELLED}
        )
        return self._resolve_pending(record, replacement)

    def cancel_for_run(self, run_id: str) -> list[ApprovalRecord]:
        """System lifecycle hook for trusted run cancellation; no client identity input."""
        return [
            self._resolve_pending(
                record,
                record.model_copy(
                    update={"status": ApprovalStatus.CANCELLED, "resolution_reason": ApprovalReason.RUN_CANCELLED}
                ),
            )
            for record in self._repository.list_pending_for_run(run_id)
        ]

    def invalidate_workspace(self, workspace_id: str) -> list[ApprovalRecord]:
        """Workspace administration hook; invalidates pending requests on revocation/change."""
        return [
            self._resolve_pending(
                record,
                record.model_copy(
                    update={
                        "status": ApprovalStatus.INVALIDATED,
                        "resolution_reason": ApprovalReason.WORKSPACE_REVOKED_OR_CHANGED,
                    }
                ),
            )
            for record in self._repository.list_pending_for_workspace(workspace_id)
        ]

    def invalidate_all_pending(
        self, reason: ApprovalReason = ApprovalReason.POLICY_OR_AUTHORITY_CHANGED
    ) -> list[ApprovalRecord]:
        """Policy hook; process bounded batches until no pending rows remain."""
        invalidated = []
        while pending := self._repository.list_pending(limit=500):
            batch = [self._invalidate_pending(record, reason) for record in pending]
            invalidated.extend(batch)
            if all(record.status == ApprovalStatus.PENDING for record in batch):
                break
        return invalidated

    def remains_valid(self, approval_id: str, *, current_request: ToolRequest) -> bool:
        """Re-check current policy; this returns a fact, never an execution token."""
        record = self._repository.get(approval_id)
        if record is None:
            return False
        record = self._expire_if_due(record)
        if record.status == ApprovalStatus.PENDING:
            trusted_request = self._current_request(record)
            if trusted_request is None:
                self._invalidate_pending(record, ApprovalReason.ELIGIBILITY_UNAVAILABLE)
                return False
            if current_request != trusted_request:
                return False
            try:
                self._require_current_operation(record, trusted_request)
            except ApprovalUnavailableError:
                self._invalidate_pending(record, self._ineligibility_reason(record))
                return False
            return True
        if record.status != ApprovalStatus.APPROVED:
            return False
        run = self._runs.get(record.run_id)
        if run is None or run.status.is_terminal or run.cancellation_requested:
            return False
        trusted_request = self._current_request(record)
        if trusted_request is None or current_request != trusted_request:
            return False
        try:
            self._require_current_operation(record, trusted_request)
        except ApprovalUnavailableError:
            return False
        return True

    def is_approved_for_execution(self, approval_id: str, *, current_request: ToolRequest) -> bool:
        """Validate an approved record against the trusted current invocation.

        This is a dispatch-time fact, not a bearer grant. The request must be
        reconstructed by the configured server-side invocation resolver, the
        durable decision must be APPROVED, and current policy/context is
        revalidated through the existing approval lifecycle.
        """
        if self._invocation_resolver is None:
            return False
        try:
            trusted = self._invocation_resolver.resolve_current_request(current_request.invocation_id)
        except Exception:
            return False
        if trusted is None or trusted != current_request:
            return False
        record = self._repository.get(approval_id)
        if record is None or record.status != ApprovalStatus.APPROVED:
            return False
        return self.remains_valid(approval_id, current_request=trusted)

    def _require_current_operation(self, record: ApprovalRecord, request: ToolRequest) -> None:
        request = ToolRequest.model_validate(request.model_dump())
        if (
            request.invocation_id != record.invocation_id
            or request.tool_id != record.tool_id
            or request.tool_version != record.tool_version
            or request.run_id != record.run_id
        ):
            raise ApprovalUnavailableError("Approval is bound to a different invocation.")
        run = self._runs.get(record.run_id)
        if run is None or run.status.is_terminal or run.cancellation_requested:
            raise ApprovalUnavailableError("The run is no longer eligible.")
        context = self._evaluate(request, record.run_id)
        decision = context.decision
        if decision.decision != ToolPolicyDecisionType.REQUIRES_APPROVAL:
            raise ApprovalUnavailableError("Current tool policy no longer permits this approval.")
        authority = context.authority
        workspace = context.workspace
        if authority is None or workspace is None or context.binding is None:
            raise ApprovalUnavailableError("Trusted operation context is unavailable.")
        if (
            context.binding != record.operation_binding
            or decision.policy_version != record.policy_version
            or decision.configuration_version != record.feature_configuration_version
            or authority.revision_ref != record.authority_revision_ref
            or authority.context.workspace_id != record.workspace_id
            or authority.context.workspace_authorization_ref != record.workspace_authorization_ref
            or workspace.configuration_revision != record.workspace_configuration_revision
        ):
            raise ApprovalUnavailableError("Approval security context has changed.")

    def _evaluate(self, request: ToolRequest, run_id: str) -> _ApprovalEvaluation:
        decision = self._policy.evaluate(ToolPolicyRequest(request=request))
        if decision.decision != ToolPolicyDecisionType.REQUIRES_APPROVAL or decision.operation_binding is None:
            return _ApprovalEvaluation(decision=decision)
        if request.run_id != run_id or self._execution_authority is None:
            raise ApprovalUnavailableError("Trusted execution authority is unavailable.")
        authority = self._execution_authority.resolve(request.execution_context_ref)
        if not isinstance(authority, ToolExecutionAuthority) or authority.run_id != run_id or authority.revoked:
            raise ApprovalUnavailableError("Trusted execution authority is unavailable.")
        context = authority.context
        if not context.workspace_id or not context.workspace_authorization_ref:
            raise ApprovalUnavailableError("Workspace authority is unavailable.")
        try:
            workspace = self._workspaces.resolve_tool_access(context.workspace_id)
        except Exception as exc:
            raise ApprovalUnavailableError("Workspace configuration is unavailable.") from exc
        feature_version = self._features.state().configuration.configuration_version
        if decision.configuration_version != feature_version:
            raise ApprovalUnavailableError("Tool feature configuration changed during approval evaluation.")
        return _ApprovalEvaluation(
            decision=decision,
            binding=decision.operation_binding,
            authority=authority,
            workspace=workspace,
        )

    def _resolve_human_authority(
        self, record: ApprovalRecord, principal: VerifiedPrincipal | None = None
    ) -> ApprovalHumanAuthority:
        try:
            authority = self._decision_authority.resolve_for(record, principal)
        except Exception as exc:
            raise ApprovalUnavailableError("Authenticated human approval authority is unavailable.") from exc
        if (
            not isinstance(authority, ApprovalHumanAuthority)
            or authority.can_decide is not True
            or record.workspace_id not in authority.workspace_ids
            or not authority.principal_ref
            or not authority.authority_revision_ref
            or (
                principal is not None
                and (
                    principal.actor_type != PrincipalActorType.HUMAN
                    or authority.principal_ref != principal.principal_ref
                )
            )
        ):
            raise ApprovalUnavailableError("Authenticated human approval authority is unavailable.")
        return authority

    def _current_request(self, record: ApprovalRecord) -> ToolRequest | None:
        try:
            candidate = (
                self._invocation_resolver.resolve_current_request(record.invocation_id)
                if self._invocation_resolver is not None
                else self._current_requests.get(record.invocation_id)
            )
            if candidate is None:
                return None
            request = ToolRequest.model_validate(candidate.model_dump())
            if (
                request.invocation_id != record.invocation_id
                or request.run_id != record.run_id
                or request.tool_id != record.tool_id
                or request.tool_version != record.tool_version
            ):
                return None
            return request
        except Exception:
            return None

    def _revalidate_pending(self, record: ApprovalRecord) -> None:
        request = self._current_request(record)
        if request is None:
            self._invalidate_pending(record, ApprovalReason.ELIGIBILITY_UNAVAILABLE)
            return
        try:
            self._require_current_operation(record, request)
        except ApprovalUnavailableError:
            self._invalidate_pending(record, self._ineligibility_reason(record))

    def _ineligibility_reason(self, record: ApprovalRecord) -> ApprovalReason:
        run = self._runs.get(record.run_id)
        if run is None or run.cancellation_requested or run.status == RunStatus.CANCELLED:
            return ApprovalReason.RUN_CANCELLED
        return ApprovalReason.ELIGIBILITY_UNAVAILABLE

    def _expire_if_due(self, record: ApprovalRecord) -> ApprovalRecord:
        if record.status != ApprovalStatus.PENDING or self._clock() < record.expires_at:
            return record
        replacement = record.model_copy(
            update={"status": ApprovalStatus.EXPIRED, "resolution_reason": ApprovalReason.EXPIRED}
        )
        return self._resolve_pending(record, replacement)

    def _invalidate_pending(self, record: ApprovalRecord, reason: ApprovalReason) -> ApprovalRecord:
        if record.status != ApprovalStatus.PENDING:
            return record
        return self._resolve_pending(
            record,
            record.model_copy(update={"status": ApprovalStatus.INVALIDATED, "resolution_reason": reason}),
        )

    def _resolve_pending(self, current: ApprovalRecord, replacement: ApprovalRecord) -> ApprovalRecord:
        resolved = self._repository.compare_and_set(current.approval_id, ApprovalStatus.PENDING, replacement)
        if resolved is not None:
            if resolved.status != ApprovalStatus.APPROVED:
                self._current_requests.pop(resolved.invocation_id, None)
            return resolved
        winner = self._repository.get(current.approval_id)
        if winner is None:
            raise ApprovalUnavailableError("Approval was not found.")
        same_resolution = winner.status == replacement.status and (
            winner.decision_metadata is not None
            and replacement.decision_metadata is not None
            and winner.decision_metadata.decision == replacement.decision_metadata.decision
            or winner.resolution_reason == replacement.resolution_reason
        )
        if same_resolution:
            if winner.status != ApprovalStatus.APPROVED:
                self._current_requests.pop(winner.invocation_id, None)
            return winner
        raise ApprovalConflictError("Approval has already been resolved.")

    @staticmethod
    def _repeat_or_conflict(record: ApprovalRecord, decision: ApprovalDecisionValue) -> ApprovalRecord:
        resolved = record.decision_metadata
        if resolved is not None and resolved.decision == decision:
            return record
        raise ApprovalConflictError("Approval has already been resolved.")

    def _clock(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("approval clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)
