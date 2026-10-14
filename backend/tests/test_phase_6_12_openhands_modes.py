"""OpenHands legacy tools are mode-gated and retain their adapter boundaries."""

from pathlib import Path

from ava.contracts.execution import ExecutionMode
from ava.contracts.runtimes import RuntimeCapabilities
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.runtimes.adapters.openhands.file_policy import FILE_EDITOR_TOOL_NAME, build_openhands_tools
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions


def _workspace(path: Path) -> RuntimeWorkspaceBinding:
    return RuntimeWorkspaceBinding(
        workspace_id="workspace-1",
        kind=WorkspaceKind.LOCAL,
        local_path=path,
        permissions=WorkspacePermissions(read=True, write=True, shell=True),
    )


def test_chat_gives_openhands_no_legacy_tools(tmp_path: Path) -> None:
    tools = build_openhands_tools(
        _workspace(tmp_path),
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        execution_mode=ExecutionMode.CHAT,
    )
    assert tools == []


def test_plan_gets_only_read_only_file_editor(tmp_path: Path) -> None:
    tools = build_openhands_tools(
        _workspace(tmp_path),
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        execution_mode=ExecutionMode.PLAN,
    )
    assert [tool.name for tool in tools] == [FILE_EDITOR_TOOL_NAME]
    assert tools[0].params == {"read_only": True}


def test_agent_legacy_tools_remain_adapter_local_and_workspace_gated(tmp_path: Path) -> None:
    tools = build_openhands_tools(
        _workspace(tmp_path),
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        execution_mode=ExecutionMode.AGENT,
    )
    assert [tool.name for tool in tools] == [FILE_EDITOR_TOOL_NAME]
    assert tools[0].params == {}
