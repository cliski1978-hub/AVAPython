"""Re-evaluated, principal and Run scoped authority for normalized tools."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ava.contracts.execution import ExecutionMode
from ava.contracts.security_identity import PrincipalValidityPort
from ava.contracts.tools import ToolExecutionContext
from ava.contracts.workspace_access import WorkspaceAccessStatus
from ava.repositories.run_repository import RunRepository
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository
from ava.repositories.workspace_grant_repository import WorkspaceGrantRepository
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_policy_service import ToolPolicyService
from ava.tools.authority import ToolExecutionAuthority, ToolExecutionAuthorityPort, ToolOperationType
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import RuntimeWorkspaceBinding, bind_workspace
from ava.workspaces.resolver import WorkspaceResolver


class RunExecutionAuthorityService(ToolExecutionAuthorityPort):
    """Issue no authority unless current durable owner, Run, grant and config agree.

    The opaque context map is only a short-lived lookup handle. Each lookup
    rebuilds the snapshot from repositories and revalidates the authentication
    session, so revocation never relies on a cached authority decision.
    """

    def __init__(
        self,
        *,
        runs: RunRepository,
        workspaces: WorkspaceResolver,
        workspace_configurations: WorkspaceAccessRepository,
        grants: WorkspaceGrantRepository,
        features: ToolFeatureService,
        registry: ToolRegistry,
        policy: ToolPolicyService,
        principal_validity: PrincipalValidityPort,
    ) -> None:
        self._runs = runs
        self._workspaces = workspaces
        self._workspace_configurations = workspace_configurations
        self._grants = grants
        self._features = features
        self._registry = registry
        self._policy = policy
        self._principal_validity = principal_validity
        self._contexts: dict[str, tuple[str, str]] = {}
        self._lock = RLock()

    def resolve_context(self, *, run_id: str, workspace_id: str | None) -> str | None:
        """Create an opaque runtime handle only for its persisted Run Workspace."""
        if not isinstance(workspace_id, str) or not workspace_id:
            return None
        run = self._runs.get(run_id)
        if (
            run is None
            or run.owner_principal_ref is None
            or run.owner_auth_context_ref is None
            or run.execution_mode == ExecutionMode.CHAT
            or run.status.is_terminal
            or run.cancellation_requested
            or run.execution_workspace_id != workspace_id
        ):
            return None
        context_ref = f"ctx-{uuid4().hex}"
        with self._lock:
            if len(self._contexts) >= 4096:
                return None
            self._contexts[context_ref] = (run_id, workspace_id)
        return context_ref

    def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
        with self._lock:
            scope = self._contexts.get(context_ref)
        if scope is None:
            return None
        run_id, workspace_id = scope
        run = self._runs.get(run_id)
        now = datetime.now(UTC)
        if (
            run is None
            or run.status.is_terminal
            or run.cancellation_requested
            or run.execution_mode == ExecutionMode.CHAT
            or run.owner_principal_ref is None
            or run.owner_auth_context_ref is None
            or run.execution_workspace_id != workspace_id
            or (run.owner_auth_valid_until is not None and run.owner_auth_valid_until <= now)
        ):
            return None
        try:
            if not self._principal_validity.is_current(run.owner_principal_ref, run.owner_auth_context_ref):
                return None
            grant = self._grants.get_active_for_principal(
                workspace_id, run.owner_principal_ref, run.owner_tenant_ref
            )
            configuration = self._workspace_configurations.get(workspace_id)
            if (
                grant is None
                or configuration is None
                or configuration.status != WorkspaceAccessStatus.ACTIVE
                or grant.status.value != "active"
                or grant.workspace_configuration_revision != configuration.revision
                or (grant.run_id is not None and grant.run_id != run_id)
                or not set(grant.capabilities).issubset(configuration.allowed_capabilities)
            ):
                return None
            resolved_workspace = self._workspaces.resolve_tool_access(workspace_id)
            binding = bind_workspace(resolved_workspace)
            feature_state = self._features.state()
            if feature_state.configuration_status != "valid" or not feature_state.framework_effective_enabled:
                return None
        except Exception:
            return None

        capabilities = frozenset(grant.capabilities) & frozenset(configuration.allowed_capabilities)
        enabled = {item.definition.tool_id for item in feature_state.tools if item.effective_enabled}
        allowed: set[str] = set()
        for definition in self._registry.list():
            operation = self._policy.operation_for_tool(definition.tool_id)
            if operation is None or operation == ToolOperationType.COMMAND:
                continue
            if run.execution_mode == ExecutionMode.PLAN and operation != ToolOperationType.READ:
                continue
            required = frozenset(definition.required_capabilities)
            if required.issubset(capabilities) and definition.tool_id in enabled:
                allowed.add(definition.tool_id)

        revision_material = "\0".join(
            (
                run.run_id,
                run.owner_principal_ref,
                run.owner_tenant_ref or "",
                run.owner_auth_context_ref,
                workspace_id,
                str(configuration.revision),
                grant.grant_id,
                str(grant.revision),
                str(feature_state.configuration.configuration_version),
                run.execution_mode.value,
            )
        )
        revision_ref = sha256(revision_material.encode("utf-8")).hexdigest()
        context = ToolExecutionContext(
            context_id=context_ref,
            workspace_id=workspace_id,
            workspace_authorization_ref=grant.grant_id,
            tool_policy_ref=f"tool-features:{feature_state.configuration.configuration_version}",
            caller_authority_ref=run.owner_principal_ref,
        )
        return ToolExecutionAuthority(
            context=context,
            workspace=RuntimeWorkspaceBinding(
                workspace_id=binding.workspace_id,
                kind=binding.kind,
                local_path=binding.local_path,
                permissions=binding.permissions,
                configuration_revision=configuration.revision,
                configured_capabilities=frozenset(capability.value for capability in capabilities),
            ),
            revision_ref=revision_ref,
            allowed_tool_ids=frozenset(allowed),
            allowed_capabilities=capabilities,
            technical_capabilities=frozenset(configuration.allowed_capabilities),
            run_id=run_id,
            principal_ref=run.owner_principal_ref,
            tenant_ref=run.owner_tenant_ref,
            grant_id=grant.grant_id,
            grant_revision=grant.revision,
            workspace_configuration_revision=configuration.revision,
            feature_configuration_version=feature_state.configuration.configuration_version,
        )


class RuntimeExecutionContextResolver:
    """Adapter from trusted run/workspace context to an opaque issuer handle."""

    def __init__(self, authority: RunExecutionAuthorityService) -> None:
        self._authority = authority

    def resolve(self, *, run_id: str, context: object, workspace: RuntimeWorkspaceBinding | None) -> str | None:
        del context
        workspace_id = workspace.workspace_id if workspace is not None else None
        return self._authority.resolve_context(run_id=run_id, workspace_id=workspace_id)
