"""Policy security matrix over isolated temporary Workspaces; no execution."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from ava.contracts.json_types import JsonValue
from ava.contracts.tool_features import UpdateToolFeaturesRequest
from ava.contracts.tool_policy import ToolPolicyDecision, ToolPolicyDecisionType, ToolPolicyReason, ToolPolicyRequest
from ava.contracts.tools import (
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolExecutionContext,
    ToolRequest,
    ToolRisk,
)
from ava.execution.command_policy import SandboxedCommandExecutionPolicy
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_feature_store import ToolFeatureStore
from ava.services.tool_policy_service import ToolPolicyService
from ava.tools.authority import ToolExecutionAuthority, ToolOperationType
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import (
    ResolvedWorkspace,
    WorkspaceInfo,
    WorkspaceKind,
    WorkspacePermissions,
    bind_workspace,
)
from ava.workspaces.registry import WorkspaceRegistry
from ava.workspaces.resolver import WorkspaceResolver


class TestFeatureAdministrator:
    __test__ = False

    def can_manage(self) -> bool:
        return True


class TestAuthorityProvider:
    __test__ = False

    def __init__(self, grant: ToolExecutionAuthority) -> None:
        self.grant: ToolExecutionAuthority | None = grant

    def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
        return self.grant if context_ref == "context-1" else None


class PolicyFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "source.txt").write_text("original")
        self.registry = ToolRegistry()
        self.operations = {f"test.{operation.value}": operation for operation in ToolOperationType}
        for tool_id, operation in self.operations.items():
            capabilities = [ToolCapability.FILE_READ]
            properties: dict[str, JsonValue] = {"path": {"type": "string", "minLength": 1}}
            required: list[JsonValue] = ["path"]
            if operation in {ToolOperationType.WRITE, ToolOperationType.EDIT, ToolOperationType.DELETE}:
                capabilities.append(ToolCapability.FILE_WRITE)
            if operation == ToolOperationType.DELETE:
                capabilities.append(ToolCapability.FILE_DELETE)
            if operation == ToolOperationType.WRITE:
                properties["content"] = {"type": "string"}
                required.append("content")
            if operation == ToolOperationType.EDIT:
                properties.update(old_text={"type": "string"}, new_text={"type": "string"})
                required.extend(["old_text", "new_text"])
            if operation == ToolOperationType.COMMAND:
                capabilities = [ToolCapability.COMMAND_EXECUTION]
                properties = {
                    "executable": {"type": "string"},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                    "working_directory": {"type": "string"},
                }
                required = ["executable"]
            self.registry.register(
                ToolDefinition(
                    tool_id=tool_id,
                    name=operation.value,
                    description="Policy fixture; no handler",
                    tool_version="1",
                    input_schema={
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                    required_capabilities=tuple(capabilities),
                    risk=ToolRisk.LOW,
                    execution_category=ToolExecutionCategory.DETERMINISTIC,
                )
            )
        self.store = ToolFeatureStore()
        self.features = ToolFeatureService(self.registry, self.store, TestFeatureAdministrator())
        self.features.update(
            UpdateToolFeaturesRequest(
                framework_enabled=True, enabled_tool_ids=tuple(self.operations), expected_version=0
            )
        )
        self.workspace = ResolvedWorkspace(
            WorkspaceInfo("workspace-1", "Test", WorkspaceKind.LOCAL),
            root,
            WorkspacePermissions(read=True, write=True, shell=True),
        )
        self.workspaces = WorkspaceRegistry()
        self.workspaces.register(self.workspace)
        capabilities_set = frozenset(
            {
                ToolCapability.FILE_READ,
                ToolCapability.FILE_WRITE,
                ToolCapability.FILE_DELETE,
                ToolCapability.COMMAND_EXECUTION,
            }
        )
        self.authority = TestAuthorityProvider(
            ToolExecutionAuthority(
                context=ToolExecutionContext(
                    context_id="context-1",
                    workspace_id="workspace-1",
                    workspace_authorization_ref="scope-1",
                    tool_policy_ref="policy-1",
                    caller_authority_ref="caller-1",
                ),
                workspace=bind_workspace(self.workspace),
                revision_ref="revision-1",
                allowed_tool_ids=frozenset(self.operations),
                allowed_capabilities=capabilities_set,
                technical_capabilities=capabilities_set,
            )
        )

    def service(self, authority: TestAuthorityProvider | None = None) -> ToolPolicyService:
        return ToolPolicyService(
            self.registry,
            self.features,
            WorkspaceResolver(self.workspaces),
            authority=authority or self.authority,
            operations=self.operations,
            command_policy=SandboxedCommandExecutionPolicy(runner_available=True),
        )

    def request(self, operation: str = "read", arguments: dict[str, JsonValue] | None = None) -> ToolPolicyRequest:
        return ToolPolicyRequest(
            request=ToolRequest(
                invocation_id="invocation-1",
                tool_id=f"test.{operation}",
                tool_version="1",
                arguments=arguments if arguments is not None else {"path": "source.txt"},
                execution_context_ref="context-1",
            )
        )


@pytest.fixture
def policy(tmp_path: Path) -> PolicyFixture:
    return PolicyFixture(tmp_path)


def test_read_preflight_has_no_side_effects_no_paths_and_stable_binding(policy: PolicyFixture) -> None:
    before = (policy.root / "source.txt").read_bytes()
    first = policy.service().evaluate(policy.request())
    assert first.decision is ToolPolicyDecisionType.ALLOW
    assert not first.execution_authorized and first.requires_execution_revalidation
    assert first == policy.service().evaluate(policy.request())
    assert str(policy.root) not in first.model_dump_json()
    assert ToolPolicyDecision.model_validate_json(first.model_dump_json()) == first
    assert (policy.root / "source.txt").read_bytes() == before
    assert list(policy.root.iterdir()) == [policy.root / "source.txt"]


@pytest.mark.parametrize("master,ids", [(False, ("test.read",)), (True, ())])
def test_disabled_gate_denies_even_with_complete_authority(
    policy: PolicyFixture, master: bool, ids: tuple[str, ...]
) -> None:
    policy.features.update(
        UpdateToolFeaturesRequest(framework_enabled=master, enabled_tool_ids=ids, expected_version=1)
    )
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.FEATURE_DISABLED


def test_unknown_version_and_unsupported_operation(policy: PolicyFixture) -> None:
    assert policy.service().evaluate(policy.request("unknown")).reason is ToolPolicyReason.UNKNOWN_TOOL
    changed = policy.request().request.model_copy(update={"tool_version": "2"})
    assert policy.service().evaluate(ToolPolicyRequest(request=changed)).reason is ToolPolicyReason.VERSION_MISMATCH
    service = ToolPolicyService(
        policy.registry, policy.features, WorkspaceResolver(policy.workspaces), authority=policy.authority
    )
    assert service.evaluate(policy.request()).reason is ToolPolicyReason.OPERATION_UNSUPPORTED


def test_missing_authority_and_legacy_workspace_selection_grant_nothing(policy: PolicyFixture) -> None:
    service = ToolPolicyService(
        policy.registry, policy.features, WorkspaceResolver(policy.workspaces), operations=policy.operations
    )
    assert service.evaluate(policy.request()).reason is ToolPolicyReason.AUTHORITY_MISSING
    policy.authority.grant = None
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.AUTHORITY_MISSING


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd"])
def test_paths_outside_approved_root_denied(policy: PolicyFixture, path: str) -> None:
    assert (
        policy.service().evaluate(policy.request(arguments={"path": path})).reason
        is ToolPolicyReason.PATH_OUTSIDE_WORKSPACE
    )


def test_symlink_escape_and_sibling_prefix_denied(policy: PolicyFixture) -> None:
    outside = policy.root.parent / f"{policy.root.name}-outside"
    outside.mkdir()
    (outside / "secret").write_text("test only")
    (policy.root / "link").symlink_to(outside, target_is_directory=True)
    for path in ("link/secret", str(outside / "secret")):
        assert (
            policy.service().evaluate(policy.request(arguments={"path": path})).reason
            is ToolPolicyReason.PATH_OUTSIDE_WORKSPACE
        )


def test_absolute_contained_path_and_normalized_relative_path(policy: PolicyFixture) -> None:
    (policy.root / "nested").mkdir()
    for path in (str(policy.root / "source.txt"), "nested/../source.txt"):
        assert (
            policy.service().evaluate(policy.request(arguments={"path": path})).decision is ToolPolicyDecisionType.ALLOW
        )


@pytest.mark.parametrize(
    "operation,args",
    [
        ("write", {"path": "new.txt", "content": "new"}),
        ("edit", {"path": "source.txt", "old_text": "original", "new_text": "new"}),
        ("delete", {"path": "source.txt"}),
    ],
)
def test_mutation_requires_approval_never_execution(
    policy: PolicyFixture, operation: str, args: dict[str, JsonValue]
) -> None:
    decision = policy.service().evaluate(policy.request(operation, args))
    assert decision.decision is ToolPolicyDecisionType.REQUIRES_APPROVAL
    assert decision.approval_required and not decision.execution_authorized
    assert decision.operation_binding is not None
    assert (policy.root / "source.txt").read_text() == "original"
    assert not (policy.root / "new.txt").exists()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"allowed_capabilities": frozenset()}, ToolPolicyReason.CAPABILITY_DENIED),
        ({"technical_capabilities": frozenset()}, ToolPolicyReason.RUNTIME_UNSUPPORTED),
        ({"allowed_tool_ids": frozenset()}, ToolPolicyReason.TOOL_NOT_AUTHORIZED),
        ({"narrowing_tool_ids": frozenset({"unrelated"})}, ToolPolicyReason.TOOL_NOT_AUTHORIZED),
        ({"revoked": True}, ToolPolicyReason.AUTHORITY_REVOKED),
        ({"run_id": "different-run"}, ToolPolicyReason.AUTHORITY_INVALID),
    ],
)
def test_authority_intersection_and_revocation(
    policy: PolicyFixture, change: dict[str, object], reason: ToolPolicyReason
) -> None:
    grant = policy.authority.grant
    assert grant is not None
    policy.authority.grant = replace(grant, **change)  # type: ignore[arg-type]
    assert policy.service().evaluate(policy.request()).reason is reason


def test_write_delete_require_scope_write_and_explicit_delete_capability(policy: PolicyFixture) -> None:
    policy.workspaces._items["workspace-1"] = replace(policy.workspace, permissions=WorkspacePermissions(read=True))
    grant = policy.authority.grant
    assert grant is not None
    policy.authority.grant = replace(grant, workspace=bind_workspace(policy.workspaces.get("workspace-1")))  # type: ignore[arg-type]
    assert policy.service().evaluate(policy.request()).decision is ToolPolicyDecisionType.ALLOW
    assert policy.service().evaluate(policy.request("delete")).reason is ToolPolicyReason.WORKSPACE_DENIED
    policy.workspaces._items["workspace-1"] = policy.workspace
    policy.authority.grant = replace(
        grant, allowed_capabilities=grant.allowed_capabilities - {ToolCapability.FILE_DELETE}
    )
    assert policy.service().evaluate(policy.request("delete")).reason is ToolPolicyReason.CAPABILITY_DENIED


def test_invalid_workspace_or_no_read_permission(policy: PolicyFixture) -> None:
    policy.workspaces._items.clear()
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.WORKSPACE_UNAVAILABLE
    policy.workspaces.register(replace(policy.workspace, permissions=WorkspacePermissions()))
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.WORKSPACE_DENIED


@pytest.mark.parametrize(
    "executable,arguments",
    [("python", ["-c", "write_files()"]), ("bash", ["script.sh"]), ("curl", ["https://example.invalid"]), ("pwd", [])],
)
def test_all_unclassified_commands_conservatively_denied(
    policy: PolicyFixture, executable: str, arguments: list[str]
) -> None:
    json_arguments: list[JsonValue] = list(arguments)
    request = policy.request("command", {"executable": executable, "arguments": json_arguments})
    assert policy.service().evaluate(request).reason is ToolPolicyReason.COMMAND_POLICY_INSUFFICIENT


def test_existing_command_policy_cwd_shell_and_network_checks(policy: PolicyFixture) -> None:
    command = policy.request("command", {"executable": "pwd", "working_directory": "../"})
    assert policy.service().evaluate(command).reason is ToolPolicyReason.COMMAND_POLICY_DENIED
    policy.workspaces._items["workspace-1"] = replace(
        policy.workspace, permissions=WorkspacePermissions(read=True, write=True)
    )
    grant = policy.authority.grant
    assert grant is not None
    policy.authority.grant = replace(grant, workspace=bind_workspace(policy.workspaces.get("workspace-1")))  # type: ignore[arg-type]
    assert (
        policy.service().evaluate(policy.request("command", {"executable": "pwd"})).reason
        is ToolPolicyReason.WORKSPACE_DENIED
    )
    policy.workspaces._items["workspace-1"] = replace(
        policy.workspace, permissions=WorkspacePermissions(read=True, write=True, shell=True, network=True)
    )
    grant = policy.authority.grant
    assert grant is not None
    policy.authority.grant = replace(grant, workspace=bind_workspace(policy.workspaces.get("workspace-1")))  # type: ignore[arg-type]
    assert (
        policy.service().evaluate(policy.request("command", {"executable": "pwd"})).reason
        is ToolPolicyReason.NETWORK_UNSUPPORTED
    )


@pytest.mark.parametrize(
    "arguments",
    [{"path": ""}, {"path": "source.txt", "permissions": True}, {"path": "source.txt", "approval": True}, {"path": 12}],
)
def test_schema_and_operation_validation(policy: PolicyFixture, arguments: dict[str, JsonValue]) -> None:
    assert policy.service().evaluate(policy.request(arguments=arguments)).reason is ToolPolicyReason.INVALID_ARGUMENTS


def test_model_runtime_and_client_authority_fields_reject_without_grants(policy: PolicyFixture) -> None:
    for field in ("model_id", "runtime_id", "authority", "workspace_id", "approval"):
        # model_construct ignores extras for frozen extra-forbid contracts;
        # real transport validation must reject them.
        with pytest.raises(ValidationError):
            ToolPolicyRequest.model_validate({"request": policy.request().request.model_dump(), field: "grant"})
        assert not policy.service().evaluate(policy.request()).execution_authorized


def test_future_allowlist_only_narrows_and_binding_changes_with_arguments_or_authority(policy: PolicyFixture) -> None:
    first = policy.service().evaluate(policy.request("write", {"path": "new.txt", "content": "one"}))
    second = policy.service().evaluate(policy.request("write", {"path": "new.txt", "content": "two"}))
    assert first.operation_binding != second.operation_binding
    grant = policy.authority.grant
    assert grant is not None
    policy.authority.grant = replace(grant, revision_ref="revision-2", narrowing_tool_ids=frozenset(policy.operations))
    third = policy.service().evaluate(policy.request("write", {"path": "new.txt", "content": "one"}))
    assert third.operation_binding != first.operation_binding
    policy.authority.grant = replace(
        grant, allowed_capabilities=frozenset(), narrowing_tool_ids=frozenset(policy.operations)
    )
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.CAPABILITY_DENIED


def test_concurrent_feature_disabling_is_observed_before_result(policy: PolicyFixture) -> None:
    entered, release = Event(), Event()
    grant = policy.authority.grant
    assert grant is not None

    class GatedProvider(TestAuthorityProvider):
        def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
            entered.set()
            assert release.wait(3)
            return super().resolve(context_ref)

    provider = GatedProvider(grant)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(policy.service(provider).evaluate, policy.request())
        assert entered.wait(3)
        policy.features.update(
            UpdateToolFeaturesRequest(
                framework_enabled=False, enabled_tool_ids=tuple(policy.operations), expected_version=1
            )
        )
        release.set()
        assert future.result(3).reason is ToolPolicyReason.FEATURE_DISABLED


def test_corrupt_configuration_denies_and_preflight_value_cannot_authorize(policy: PolicyFixture) -> None:
    policy.store._configuration = policy.features.state().configuration.model_copy(update={"framework_enabled": "bad"})
    decision = policy.service().evaluate(policy.request())
    assert decision.reason is ToolPolicyReason.CONFIGURATION_INVALID
    with pytest.raises(ValidationError):
        ToolPolicyDecision.model_validate({**decision.model_dump(), "execution_authorized": True})


def test_workspace_root_pin_prevents_retargeting_a_granted_identity(policy: PolicyFixture) -> None:
    outside = policy.root.parent / f"{policy.root.name}-new-root"
    outside.mkdir()
    (outside / "source.txt").write_text("different scope")
    policy.workspaces._items["workspace-1"] = replace(policy.workspace, root_path=outside)
    assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.WORKSPACE_CHANGED


def test_changing_technical_support_cannot_increase_caller_permissions(policy: PolicyFixture) -> None:
    grant = policy.authority.grant
    assert grant is not None
    for technical in (frozenset(), grant.technical_capabilities):
        policy.authority.grant = replace(grant, technical_capabilities=technical, allowed_capabilities=frozenset())
        assert policy.service().evaluate(policy.request()).reason is ToolPolicyReason.CAPABILITY_DENIED


def test_authority_and_scope_changes_during_preflight_deny(policy: PolicyFixture) -> None:
    grant = policy.authority.grant
    assert grant is not None

    class RevokingProvider(TestAuthorityProvider):
        calls = 0

        def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
            self.calls += 1
            assert self.grant is not None
            return self.grant if self.calls == 1 else replace(self.grant, revoked=True)

    assert (
        policy.service(RevokingProvider(grant)).evaluate(policy.request()).reason is ToolPolicyReason.AUTHORITY_CHANGED
    )


def test_required_read_approval_metadata_is_not_bypassed(policy: PolicyFixture) -> None:
    catalog = ToolRegistry()
    for definition in policy.registry.list():
        if definition.tool_id == "test.read":
            definition = definition.model_copy(update={"approval_requirement": "required"})
        catalog.register(definition)
    service = ToolPolicyService(
        catalog,
        ToolFeatureService(catalog, policy.store),
        WorkspaceResolver(policy.workspaces),
        authority=policy.authority,
        operations=policy.operations,
    )
    decision = service.evaluate(policy.request())
    assert decision.decision is ToolPolicyDecisionType.REQUIRES_APPROVAL
    assert not decision.execution_authorized


def test_malformed_candidates_and_forged_decision_combinations_reject(policy: PolicyFixture) -> None:
    malformed = ToolPolicyRequest.model_construct(
        request=policy.request().request.model_copy(update={"arguments": {"path": object()}})
    )
    assert policy.service().evaluate(malformed).reason is ToolPolicyReason.INVALID_REQUEST
    allowed = policy.service().evaluate(policy.request())
    with pytest.raises(ValidationError):
        ToolPolicyDecision.model_validate({**allowed.model_dump(), "reason": "unknown_tool"})


def test_default_application_composition_has_no_authority_or_classifications() -> None:
    from ava.api.app import create_app
    from ava.configuration.settings import Settings

    app = create_app(settings=Settings(persistence_provider="memory", attachment_storage="memory"))
    assert isinstance(app.state.tool_policy_service, ToolPolicyService)
    assert (
        app.state.tool_policy_service.evaluate(
            ToolPolicyRequest(
                request=ToolRequest(
                    invocation_id="inv",
                    tool_id="test.read",
                    tool_version="1",
                    arguments={"path": "source.txt"},
                    execution_context_ref="ctx",
                )
            )
        ).decision
        is ToolPolicyDecisionType.DENY
    )
    assert not any(getattr(route, "path", "").startswith("/tool-policy") for route in app.routes)
    app.state.persistence.dispose()
