"""Central normalized-tool preflight; never executes or issues approvals."""

import hashlib
import json
import stat as stat_types
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, StrictStr, TypeAdapter, ValidationError

from ava.contracts.json_types import JsonValue
from ava.contracts.tool_policy import ToolPolicyDecision, ToolPolicyDecisionType, ToolPolicyReason, ToolPolicyRequest
from ava.contracts.tools import (
    ToolApprovalRequirement,
    ToolCapability,
    ToolExecutionContext,
    ToolIdentifier,
    ToolOperationBinding,
    ToolReference,
    ToolRequest,
    ToolRisk,
)
from ava.execution.command_policy import CommandExecutionPolicy, CommandRequest
from ava.services.tool_feature_service import ToolFeatureService, ToolFeatureUnavailableError
from ava.tools.authority import ToolExecutionAuthority, ToolExecutionAuthorityPort, ToolOperationType
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import ResolvedWorkspace, RuntimeWorkspaceBinding, WorkspacePermissions, bind_workspace
from ava.workspaces.resolver import WorkspaceResolver


class _FileArguments(BaseModel):
    # The selected definition's strict JSON schema has already rejected
    # unknown keys; tool-specific read options must remain available here.
    model_config = ConfigDict(extra="allow")
    path: StrictStr


class _WriteArguments(_FileArguments):
    content: StrictStr


class _EditArguments(_FileArguments):
    old_text: StrictStr
    new_text: StrictStr


class _CommandArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executable: StrictStr
    arguments: list[StrictStr] = []
    working_directory: StrictStr | None = None


_MINIMUM_CAPABILITIES = {
    ToolOperationType.READ: frozenset({ToolCapability.FILE_READ}),
    ToolOperationType.WRITE: frozenset({ToolCapability.FILE_READ, ToolCapability.FILE_WRITE}),
    ToolOperationType.EDIT: frozenset({ToolCapability.FILE_READ, ToolCapability.FILE_WRITE}),
    ToolOperationType.DELETE: frozenset(
        {ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE}
    ),
    ToolOperationType.COMMAND: frozenset({ToolCapability.COMMAND_EXECUTION}),
}


def _matches_schema(value: JsonValue, schema: dict[str, JsonValue]) -> bool:
    """Validate instances against the already-validated Phase 6.2 subset."""
    kind = schema["type"]
    valid_type = {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if not isinstance(kind, str) or not valid_type.get(kind, False):
        return False
    enum = schema.get("enum")
    if isinstance(enum, list) and not any(
        json.dumps(value, sort_keys=True) == json.dumps(item, sort_keys=True) for item in enum
    ):
        return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return False
        if any(not isinstance(name, str) or name not in value for name in required):
            return False
        for name, child in value.items():
            child_schema = properties.get(name, schema.get("additionalProperties", True))
            if child_schema is False:
                return False
            if isinstance(child_schema, dict) and not _matches_schema(child, child_schema):
                return False
    if isinstance(value, list):
        items = schema.get("items")
        if not isinstance(items, dict) or any(not _matches_schema(child, items) for child in value):
            return False
    for minimum, maximum, actual in (
        ("minLength", "maxLength", len(value) if isinstance(value, str) else None),
        ("minItems", "maxItems", len(value) if isinstance(value, list) else None),
        ("minimum", "maximum", value if type(value) in (int, float) else None),
    ):
        if not isinstance(actual, (int, float)):
            continue
        lower, upper = schema.get(minimum), schema.get(maximum)
        if isinstance(lower, (int, float)) and actual < lower:
            return False
        if isinstance(upper, (int, float)) and actual > upper:
            return False
    return True


class ToolPolicyService:
    def __init__(
        self,
        registry: ToolRegistry,
        features: ToolFeatureService,
        workspaces: WorkspaceResolver,
        *,
        authority: ToolExecutionAuthorityPort | None = None,
        operations: Mapping[str, ToolOperationType] | None = None,
        command_policy: CommandExecutionPolicy | None = None,
        policy_version: str = "tool-policy-v1",
    ) -> None:
        self._registry = registry
        self._features = features
        self._workspaces = workspaces
        self._authority = authority
        # Trusted operation classifications, not user scripts or registry grants.
        self._operations = MappingProxyType(dict(operations or {}))
        self._command_policy = command_policy
        self._version = TypeAdapter(ToolReference).validate_python(policy_version)

    def operation_for_tool(self, tool_id: str) -> ToolOperationType | None:
        """Return the trusted structured effect classification, if registered."""
        operation = self._operations.get(tool_id)
        return operation if isinstance(operation, ToolOperationType) else None

    def _decision(
        self,
        reason: ToolPolicyReason,
        request: ToolRequest | None = None,
        *,
        version: int | None = None,
        binding: ToolOperationBinding | None = None,
        approval: bool = False,
    ) -> ToolPolicyDecision:
        decision = ToolPolicyDecisionType.DENY
        if reason == ToolPolicyReason.ALLOWED:
            decision = ToolPolicyDecisionType.ALLOW
        elif reason == ToolPolicyReason.APPROVAL_REQUIRED:
            decision = ToolPolicyDecisionType.REQUIRES_APPROVAL
        return ToolPolicyDecision(
            invocation_id=request.invocation_id if request else None,
            tool_id=request.tool_id if request else None,
            decision=decision,
            reason=reason,
            explanation=f"AVA preflight policy: {reason.value.replace('_', ' ')}.",
            configuration_version=version,
            policy_version=self._version,
            operation_binding=binding,
            approval_required=approval,
        )

    def evaluate(self, candidate: ToolPolicyRequest) -> ToolPolicyDecision:
        """Return current policy eligibility; no durable lease or execution grant."""
        if not isinstance(candidate, ToolPolicyRequest):
            return self._decision(ToolPolicyReason.INVALID_REQUEST)
        try:
            request = ToolPolicyRequest.model_validate(candidate.model_dump(warnings=False)).request
        except (ValueError, TypeError, AttributeError):
            return self._decision(ToolPolicyReason.INVALID_REQUEST)
        definition = self._registry.get(request.tool_id)
        if definition is None:
            return self._decision(ToolPolicyReason.UNKNOWN_TOOL, request)
        if request.tool_version != definition.tool_version:
            return self._decision(ToolPolicyReason.VERSION_MISMATCH, request)
        feature = self._features.state()
        version = feature.configuration.configuration_version
        try:
            self._features.require_enabled(request.tool_id)
        except ToolFeatureUnavailableError:
            reason = (
                ToolPolicyReason.CONFIGURATION_INVALID
                if feature.configuration_status == "invalid"
                else ToolPolicyReason.FEATURE_DISABLED
            )
            return self._decision(reason, request, version=version)
        operation = self._operations.get(request.tool_id)
        if not isinstance(operation, ToolOperationType):
            return self._decision(ToolPolicyReason.OPERATION_UNSUPPORTED, request, version=version)
        if not _matches_schema(request.arguments, definition.input_schema):
            return self._decision(ToolPolicyReason.INVALID_ARGUMENTS, request, version=version)
        try:
            if operation == ToolOperationType.COMMAND:
                arguments: _FileArguments | _CommandArguments = _CommandArguments.model_validate(request.arguments)
            else:
                argument_types: dict[ToolOperationType, type[_FileArguments]] = {
                    ToolOperationType.WRITE: _WriteArguments,
                    ToolOperationType.EDIT: _EditArguments,
                }
                argument_type = argument_types.get(operation, _FileArguments)
                arguments = argument_type.model_validate(request.arguments)
            grant = self._authority.resolve(request.execution_context_ref) if self._authority else None
        except ValidationError:
            return self._decision(ToolPolicyReason.INVALID_ARGUMENTS, request, version=version)
        except Exception:
            return self._decision(ToolPolicyReason.AUTHORITY_INVALID, request, version=version)
        if grant is None:
            return self._decision(ToolPolicyReason.AUTHORITY_MISSING, request, version=version)
        if not isinstance(grant, ToolExecutionAuthority):
            return self._decision(ToolPolicyReason.AUTHORITY_INVALID, request, version=version)
        context = grant.context
        try:
            if not isinstance(context, ToolExecutionContext) or not isinstance(
                grant.workspace, RuntimeWorkspaceBinding
            ):
                raise ValueError("invalid context")
            context = ToolExecutionContext.model_validate(context.model_dump())
            if type(grant.revoked) is not bool:
                raise ValueError("invalid revocation state")
            TypeAdapter(ToolReference).validate_python(grant.revision_ref)
            for values in (grant.allowed_capabilities, grant.technical_capabilities):
                if not isinstance(values, frozenset) or any(not isinstance(value, ToolCapability) for value in values):
                    raise ValueError("invalid capabilities")
            for ids in (grant.allowed_tool_ids, grant.narrowing_tool_ids):
                if ids is not None:
                    if not isinstance(ids, frozenset):
                        raise ValueError("invalid allowlist")
                    for tool_id in ids:
                        TypeAdapter(ToolIdentifier).validate_python(tool_id)
        except (ValueError, TypeError, AttributeError):
            return self._decision(ToolPolicyReason.AUTHORITY_INVALID, request, version=version)
        if (
            context.context_id != request.execution_context_ref
            or grant.run_id != request.run_id
            or not all(
                (
                    context.workspace_id,
                    context.workspace_authorization_ref,
                    context.tool_policy_ref,
                    context.caller_authority_ref,
                    grant.revision_ref,
                )
            )
        ):
            return self._decision(ToolPolicyReason.AUTHORITY_INVALID, request, version=version)
        if grant.revoked:
            return self._decision(ToolPolicyReason.AUTHORITY_REVOKED, request, version=version)
        if request.tool_id not in grant.allowed_tool_ids or (
            grant.narrowing_tool_ids is not None and request.tool_id not in grant.narrowing_tool_ids
        ):
            return self._decision(ToolPolicyReason.TOOL_NOT_AUTHORIZED, request, version=version)
        required = _MINIMUM_CAPABILITIES[operation] | frozenset(definition.required_capabilities)
        if not required.issubset(definition.required_capabilities):
            return self._decision(ToolPolicyReason.CONFIGURATION_INVALID, request, version=version)
        if ToolCapability.NETWORK_ACCESS in required:
            return self._decision(ToolPolicyReason.NETWORK_UNSUPPORTED, request, version=version)
        if not required.issubset(grant.allowed_capabilities):
            return self._decision(ToolPolicyReason.CAPABILITY_DENIED, request, version=version)
        if not required.issubset(grant.technical_capabilities):
            return self._decision(ToolPolicyReason.RUNTIME_UNSUPPORTED, request, version=version)
        try:
            assert context.workspace_id is not None
            workspace = self._workspaces.resolve_tool_access(context.workspace_id)
            if workspace.root_path is None or not workspace.root_path.is_absolute():
                raise ValueError("missing root")
            if not isinstance(workspace.permissions, WorkspacePermissions) or any(
                type(value) is not bool
                for value in (
                    workspace.permissions.read,
                    workspace.permissions.write,
                    workspace.permissions.shell,
                    workspace.permissions.network,
                )
            ):
                raise ValueError("invalid permissions")
            root = workspace.root_path.resolve(strict=True)
            if not root.is_dir():
                raise ValueError("invalid root")
        except (ValueError, OSError, RuntimeError, TypeError, AttributeError):
            return self._decision(ToolPolicyReason.WORKSPACE_UNAVAILABLE, request, version=version)
        if not workspace.permissions.read or (operation != ToolOperationType.READ and not workspace.permissions.write):
            return self._decision(ToolPolicyReason.WORKSPACE_DENIED, request, version=version)
        if workspace.configured_capabilities is not None:
            if not isinstance(workspace.configured_capabilities, frozenset) or any(
                type(value) is not str for value in workspace.configured_capabilities
            ):
                return self._decision(ToolPolicyReason.CONFIGURATION_INVALID, request, version=version)
            if not {capability.value for capability in required}.issubset(workspace.configured_capabilities):
                return self._decision(ToolPolicyReason.CAPABILITY_DENIED, request, version=version)
        # Issuers pin the canonical root and grants, not just a mutable ID.
        if (
            grant.workspace.workspace_id != context.workspace_id
            or grant.workspace.local_path != root
            or grant.workspace.permissions != workspace.permissions
            or grant.workspace.kind != workspace.info.kind
            or grant.workspace.configuration_revision != workspace.configuration_revision
            or grant.workspace.configured_capabilities != workspace.configured_capabilities
        ):
            return self._decision(ToolPolicyReason.WORKSPACE_CHANGED, request, version=version)
        if isinstance(arguments, _CommandArguments):
            return self._command(request, arguments, workspace, version)
        if not arguments.path.strip() or "\x00" in arguments.path:
            return self._decision(ToolPolicyReason.INVALID_ARGUMENTS, request, version=version)
        try:
            # Same canonical descendant rule as Phase 3, never a string prefix.
            path = (root / arguments.path).resolve(strict=False)
            relative = path.relative_to(root)
        except (OSError, ValueError, RuntimeError):
            return self._decision(ToolPolicyReason.PATH_OUTSIDE_WORKSPACE, request, version=version)
        list_directory = request.tool_id == "workspace.list_files"
        try:
            if list_directory:
                unsupported = not path.is_dir()
            else:
                unsupported = path == root or (path.exists() and (not path.is_file() or path.stat().st_nlink > 1))
            if (
                operation in {ToolOperationType.READ, ToolOperationType.EDIT, ToolOperationType.DELETE}
                and not list_directory
            ):
                unsupported = unsupported or not path.is_file()
        except OSError:
            unsupported = True
        if unsupported:
            return self._decision(ToolPolicyReason.RESOURCE_UNSUPPORTED, request, version=version)
        try:
            current_grant = self._authority.resolve(request.execution_context_ref) if self._authority else None
            current_workspace = self._workspaces.resolve_tool_access(context.workspace_id)
            if current_grant != grant:
                return self._decision(ToolPolicyReason.AUTHORITY_CHANGED, request, version=version)
            if current_workspace != workspace or workspace.root_path.resolve(strict=True) != root:
                return self._decision(ToolPolicyReason.WORKSPACE_CHANGED, request, version=version)
            final_features = self._features.state()
            self._features.require_enabled(request.tool_id)
            if final_features.configuration.configuration_version != version:
                return self._decision(ToolPolicyReason.CONFIGURATION_CHANGED, request, version=version)
            if (root / arguments.path).resolve(strict=False) != path:
                return self._decision(ToolPolicyReason.PATH_OUTSIDE_WORKSPACE, request, version=version)
            stat = path.stat() if path.exists() else None
            if stat is not None and (
                (not stat_types.S_ISDIR(stat.st_mode) if list_directory else not stat_types.S_ISREG(stat.st_mode))
                or (not stat_types.S_ISDIR(stat.st_mode) and stat.st_nlink > 1)
            ):
                return self._decision(ToolPolicyReason.RESOURCE_UNSUPPORTED, request, version=version)
            if stat is None and operation in {ToolOperationType.READ, ToolOperationType.EDIT, ToolOperationType.DELETE}:
                return self._decision(ToolPolicyReason.RESOURCE_UNSUPPORTED, request, version=version)
        except ToolFeatureUnavailableError:
            return self._decision(ToolPolicyReason.FEATURE_DISABLED, request, version=version)
        except Exception:
            return self._decision(ToolPolicyReason.WORKSPACE_CHANGED, request, version=version)
        operation_data = {
            "request": request.model_dump(mode="json"),
            "definition": definition.model_dump(mode="json"),
            "workspace_id": context.workspace_id,
            "root": str(root),
            "relative_target": str(relative),
            "authority": context.model_dump(mode="json"),
            "authority_revision": grant.revision_ref,
            "allowed_tools": sorted(grant.allowed_tool_ids),
            "narrowing_tools": sorted(grant.narrowing_tool_ids) if grant.narrowing_tool_ids is not None else None,
            "allowed_capabilities": sorted(grant.allowed_capabilities),
            "technical_capabilities": sorted(grant.technical_capabilities),
            "workspace_permissions": {
                "read": workspace.permissions.read,
                "write": workspace.permissions.write,
                "shell": workspace.permissions.shell,
                "network": workspace.permissions.network,
            },
            "policy_version": self._version,
            "configuration_version": version,
            "resource_stat": [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns] if stat else None,
            "operation": operation.value,
        }
        digest = hashlib.sha256(
            json.dumps(operation_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        binding = ToolOperationBinding(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            tool_version=request.tool_version,
            execution_context_ref=request.execution_context_ref,
            operation_digest=digest,
            authority_revision_ref=grant.revision_ref,
        )
        approval = (
            operation != ToolOperationType.READ
            or definition.approval_requirement == ToolApprovalRequirement.REQUIRED
            or definition.risk != ToolRisk.LOW
        )
        return self._decision(
            ToolPolicyReason.APPROVAL_REQUIRED if approval else ToolPolicyReason.ALLOWED,
            request,
            version=version,
            binding=binding,
            approval=approval,
        )

    def _command(
        self,
        request: ToolRequest,
        arguments: _CommandArguments,
        workspace: ResolvedWorkspace,
        version: int,
    ) -> ToolPolicyDecision:
        if not workspace.permissions.shell:
            return self._decision(ToolPolicyReason.WORKSPACE_DENIED, request, version=version)
        if workspace.permissions.network:
            return self._decision(ToolPolicyReason.NETWORK_UNSUPPORTED, request, version=version)
        if self._command_policy is None:
            return self._decision(ToolPolicyReason.COMMAND_UNAVAILABLE, request, version=version)
        try:
            decision = self._command_policy.evaluate(
                workspace=bind_workspace(workspace),
                command=CommandRequest(
                    executable=arguments.executable,
                    arguments=tuple(arguments.arguments),
                    working_directory=arguments.working_directory,
                ),
            )
        except Exception:
            return self._decision(ToolPolicyReason.COMMAND_POLICY_DENIED, request, version=version)
        if not decision.allowed:
            return self._decision(ToolPolicyReason.COMMAND_POLICY_DENIED, request, version=version)
        # The current policy validates syntax/cwd, but not argument effects or
        # the runner's executable allowlist. No approval may bypass that gap.
        return self._decision(ToolPolicyReason.COMMAND_POLICY_INSUFFICIENT, request, version=version)
