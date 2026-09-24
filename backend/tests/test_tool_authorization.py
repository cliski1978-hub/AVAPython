"""Pure, model-independent Step 36 activation matrix (no SDK or sandbox)."""

from pathlib import Path

import pytest

from ava.contracts.runtimes import RuntimeCapabilities
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions


@pytest.mark.parametrize("capable", [False, True], ids=["native", "coding-runtime"])
@pytest.mark.parametrize("tool_id", ["file_editor", "ava_terminal", "unknown_tool"])
@pytest.mark.parametrize("permissions", [
    None, WorkspacePermissions(), WorkspacePermissions(read=True),
    WorkspacePermissions(read=True, write=True), WorkspacePermissions(read=True, write=True, shell=True),
    WorkspacePermissions(read=False, write=True, shell=True),
])
def test_activation_matrix(capable: bool, tool_id: str, permissions: WorkspacePermissions | None) -> None:
    workspace = None if permissions is None else RuntimeWorkspaceBinding(
        "approved", WorkspaceKind.LOCAL, Path("/server-owned"), permissions,
    )
    decision = ToolAuthorizationPolicy().evaluate(
        tool_id=tool_id, workspace=workspace,
        capabilities=RuntimeCapabilities(tools=capable, filesystem=capable, shell=capable),
    )
    expected = bool(
        capable and tool_id != "unknown_tool" and permissions and permissions.read
        and (tool_id == "file_editor" or permissions.shell)
    )
    assert decision.allowed is expected
    assert decision.reason_code == ("allowed" if expected else (
        "tool_not_approved" if tool_id == "unknown_tool" else
        "runtime_capability_missing" if not capable else
        "workspace_required" if permissions is None else
        "workspace_read_denied" if not permissions.read else "workspace_shell_denied"
    ))


def test_network_permission_does_not_enable_network_tool() -> None:
    decision = ToolAuthorizationPolicy().evaluate(
        tool_id="ava_terminal", capabilities=RuntimeCapabilities(tools=True, shell=True),
        workspace=RuntimeWorkspaceBinding(
            "approved", WorkspaceKind.LOCAL, Path("/server-owned"),
            WorkspacePermissions(read=True, shell=True, network=True),
        ),
    )
    assert not decision.allowed
    assert decision.reason_code == "network_policy_unsupported"
