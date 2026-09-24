"""Real SDK executor integration without model inference."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("openhands.tools.file_editor")
from openhands.tools.file_editor.definition import FileEditorAction  # noqa: E402

from ava.contracts.runtimes import RuntimeCapabilities  # noqa: E402
from ava.execution.command_policy import SandboxedCommandExecutionPolicy  # noqa: E402
from ava.execution.sandbox import SandboxedCommandResult  # noqa: E402
from ava.execution.tool_security import (  # noqa: E402
    InMemoryToolAuditSink,
    ToolAuthorizationPolicy,
    ToolRunContext,
)
from ava.runtimes.adapters.openhands.controlled_terminal import (  # noqa: E402
    AvaTerminalAction,
    AvaTerminalExecutor,
)
from ava.runtimes.adapters.openhands.file_policy import build_openhands_tools  # noqa: E402
from ava.runtimes.adapters.openhands.file_tools import ContainedFileEditorExecutor  # noqa: E402
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions  # noqa: E402


@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize("command", ["view", "create", "delete"])
def test_file_operation_matrix(tmp_path: Path, write: bool, command: str) -> None:
    sink = InMemoryToolAuditSink()
    executor = ContainedFileEditorExecutor(
        str(tmp_path), read_only=not write, context=ToolRunContext("run", "runtime", sink),
    )
    target = tmp_path / "data"
    if command != "create":
        target.write_text("AVA_FAKE_SECRET_DO_NOT_LEAK")
    # model_construct exercises the defensive deletion gate behind SDK schema validation.
    action = FileEditorAction.model_construct(command=command, path=str(target), file_text="new contents")
    if command == "delete":
        from openhands.tools.file_editor.exceptions import ToolError

        with pytest.raises(ToolError, match="deletion is disabled"):
            executor.editor(command="delete", path=str(target))
        assert target.exists()
        return
    result = executor(action)
    allowed = command == "view" or (command == "create" and write)
    assert result.is_error is not allowed
    event, = sink.events
    assert event.outcome == ("success" if allowed else "denied")
    if command == "delete":
        assert event.reason_code == "delete_not_authorized"
        assert target.exists()
    elif not allowed:
        assert event.reason_code == "write_not_authorized"
    assert str(tmp_path) not in str(sink.events)
    assert "AVA_FAKE_SECRET_DO_NOT_LEAK" not in str(sink.events)
    assert "new contents" not in str(sink.events)


def test_missing_policy_and_capabilities_fail_closed(tmp_path: Path) -> None:
    workspace = RuntimeWorkspaceBinding(
        "approved", WorkspaceKind.LOCAL, tmp_path, WorkspacePermissions(read=True, write=True, shell=True),
    )
    assert build_openhands_tools(workspace) == []
    assert build_openhands_tools(workspace, authorization_policy=ToolAuthorizationPolicy()) == []
    sink = InMemoryToolAuditSink()
    assert build_openhands_tools(
        None, authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True), context=ToolRunContext("r", "rt", sink),
    ) == []
    assert all(event.outcome == "denied" for event in sink.events)


@pytest.mark.parametrize("failure", ["escape", "missing", "replacement"])
def test_file_failures_are_sanitized(tmp_path: Path, failure: str) -> None:
    root = tmp_path / "ava-secret-root-123"
    root.mkdir()
    target = root / "file"
    target.write_text("AVA_FAKE_SECRET_DO_NOT_LEAK")
    executor = ContainedFileEditorExecutor(str(root))
    action = FileEditorAction(
        command="str_replace" if failure == "replacement" else "view",
        path=str(target if failure == "replacement" else root / ("missing" if failure == "missing" else "../escape")),
        old_str="secret replacement input", new_str="value",
    )
    result = executor(action)
    assert result.is_error
    assert str(tmp_path) not in result.text
    assert "AVA_FAKE_SECRET_DO_NOT_LEAK" not in result.text
    assert "secret replacement input" not in result.text


class StubRunner:
    calls = 0
    exit_code = 1

    async def execute(self, request: Any) -> SandboxedCommandResult:
        self.calls += 1
        return SandboxedCommandResult(self.exit_code, "bounded output", "")

    async def cancel(self, command_id: str) -> None:
        pass


@pytest.mark.parametrize("exit_code", [0, 1])
def test_command_denied_success_failure_and_revocation(tmp_path: Path, exit_code: int) -> None:
    sink = InMemoryToolAuditSink()
    context = ToolRunContext("r", "rt", sink)
    runner = StubRunner()
    runner.exit_code = exit_code
    executor = AvaTerminalExecutor(
        workspace=RuntimeWorkspaceBinding(
            "approved", WorkspaceKind.LOCAL, tmp_path, WorkspacePermissions(read=True, shell=True),
        ), policy=SandboxedCommandExecutionPolicy(runner_available=True), runner=runner, context=context,
    )
    assert executor(AvaTerminalAction(executable="/bin/sh")).is_error
    assert runner.calls == 0
    assert sink.events[-1].outcome == "denied"
    assert executor(AvaTerminalAction(executable="pwd")).exit_code == exit_code
    assert sink.events[-1].reason_code == ("command_nonzero_exit" if exit_code else "allowed")
    assert sink.events[-1].outcome == ("failure" if exit_code else "success")
    context.revoked.set()
    assert executor(AvaTerminalAction(executable="pwd")).is_error
    assert runner.calls == 1
    assert sink.events[-1].reason_code == "run_cancelled"
    file = ContainedFileEditorExecutor(str(tmp_path), context=context)
    assert file(FileEditorAction(command="create", path=str(tmp_path / "blocked"), file_text="x")).is_error
    assert not (tmp_path / "blocked").exists()


def test_revocation_is_run_scoped_between_parallel_runs(tmp_path: Path) -> None:
    sink = InMemoryToolAuditSink()
    revoked = ToolRunContext("revoked-run", "runtime", sink)
    active = ToolRunContext("active-run", "runtime", sink)
    revoked.revoked.set()
    revoked_file = ContainedFileEditorExecutor(str(tmp_path), context=revoked)
    active_file = ContainedFileEditorExecutor(str(tmp_path), context=active)
    denied = revoked_file(FileEditorAction(command="create", path=str(tmp_path / "revoked"), file_text="x"))
    assert denied.is_error
    assert not (tmp_path / "revoked").exists()
    allowed = active_file(FileEditorAction(command="create", path=str(tmp_path / "active"), file_text="x"))
    assert not allowed.is_error
    assert (tmp_path / "active").exists()
    assert not active.revoked.is_set()

    class Runner(StubRunner):
        async def execute(self, request: Any) -> SandboxedCommandResult:
            self.calls += 1
            return SandboxedCommandResult(0, "ok", "")

    workspace = RuntimeWorkspaceBinding(
        "approved", WorkspaceKind.LOCAL, tmp_path, WorkspacePermissions(read=True, shell=True),
    )
    policy = SandboxedCommandExecutionPolicy(runner_available=True)
    active_runner = Runner()
    active_terminal = AvaTerminalExecutor(
        workspace=workspace, policy=policy, runner=active_runner, context=active,
    )
    revoked_terminal = AvaTerminalExecutor(
        workspace=workspace, policy=policy, runner=Runner(), context=revoked,
    )
    assert revoked_terminal(AvaTerminalAction(executable="pwd")).is_error
    active_result = active_terminal(AvaTerminalAction(executable="pwd"))
    assert not active_result.is_error
    assert active_result.exit_code == 0
    assert active_runner.calls == 1


def test_command_exceptions_are_sanitized(tmp_path: Path) -> None:
    class BrokenRunner(StubRunner):
        async def execute(self, request: Any) -> SandboxedCommandResult:
            raise OSError("/tmp/ava-secret-root-123 AVA_FAKE_SECRET_DO_NOT_LEAK")

    executor = AvaTerminalExecutor(
        workspace=RuntimeWorkspaceBinding(
            "approved", WorkspaceKind.LOCAL, tmp_path, WorkspacePermissions(read=True, shell=True),
        ), policy=SandboxedCommandExecutionPolicy(runner_available=True), runner=BrokenRunner(),
    )
    result = executor(AvaTerminalAction(executable="pwd"))
    assert result.text == "Command execution failed"


def test_revocation_cancels_active_command_on_its_own_event_loop(tmp_path: Path) -> None:
    context = ToolRunContext("r", "rt")

    class RevokingRunner(StubRunner):
        cancelled = False

        async def execute(self, request: Any) -> SandboxedCommandResult:
            context.revoked.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self.cancelled = True
            return SandboxedCommandResult(None, "", "", cancelled=True, reason_code="cancelled")

    runner = RevokingRunner()
    executor = AvaTerminalExecutor(
        workspace=RuntimeWorkspaceBinding(
            "approved", WorkspaceKind.LOCAL, tmp_path, WorkspacePermissions(read=True, shell=True),
        ), policy=SandboxedCommandExecutionPolicy(runner_available=True), runner=runner, context=context,
    )
    assert executor(AvaTerminalAction(executable="pwd")).cancelled
    assert runner.cancelled
