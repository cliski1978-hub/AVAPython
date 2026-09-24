"""Step 34 command-policy security boundary tests.

These tests exercise only AVA's runtime-neutral policy.  They never launch a
host process: a policy approval is intentionally impossible without a future
sandbox runner.
"""

import os
from pathlib import Path

from ava.execution.command_policy import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    MINIMAL_COMMAND_ENVIRONMENT,
    CommandRequest,
    SandboxedCommandExecutionPolicy,
)
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions


def _workspace(root: Path | None, *, shell: bool = True) -> RuntimeWorkspaceBinding:
    return RuntimeWorkspaceBinding(
        workspace_id="command-policy-test",
        kind=WorkspaceKind.LOCAL,
        local_path=root,
        permissions=WorkspacePermissions(read=True, write=True, shell=shell),
    )


def test_shell_permission_is_required(tmp_path: Path) -> None:
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(tmp_path, shell=False), command=CommandRequest(executable="pwd")
    )
    assert not decision.allowed
    assert decision.reason_code == "shell_permission_required"


def test_local_workspace_is_required() -> None:
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(None), command=CommandRequest(executable="pwd")
    )
    assert not decision.allowed
    assert decision.reason_code == "local_workspace_required"


def test_shell_grant_still_requires_a_sandbox(tmp_path: Path) -> None:
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(tmp_path), command=CommandRequest(executable="pwd")
    )
    assert not decision.allowed
    assert decision.reason_code == "sandbox_required"
    assert decision.working_directory == tmp_path.resolve()
    assert decision.timeout_seconds == DEFAULT_COMMAND_TIMEOUT_SECONDS


def test_contained_relative_working_directory_is_resolved(tmp_path: Path) -> None:
    subdirectory = tmp_path / "subdirectory"
    subdirectory.mkdir()
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(tmp_path), command=CommandRequest(executable="pwd", working_directory="subdirectory")
    )
    assert decision.reason_code == "sandbox_required"
    assert decision.working_directory == subdirectory.resolve()


def test_absolute_and_dotdot_working_directory_escapes_are_denied(tmp_path: Path) -> None:
    policy = SandboxedCommandExecutionPolicy()
    outside = tmp_path.parent
    for directory in (str(outside), "../outside"):
        decision = policy.evaluate(
            workspace=_workspace(tmp_path), command=CommandRequest(executable="pwd", working_directory=directory)
        )
        assert not decision.allowed
        assert decision.reason_code == "working_directory_outside_workspace"


def test_symlinked_working_directory_escape_is_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "outside-link").symlink_to(outside, target_is_directory=True)
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(tmp_path), command=CommandRequest(executable="pwd", working_directory="outside-link")
    )
    assert not decision.allowed
    assert decision.reason_code == "working_directory_outside_workspace"


def test_only_a_bare_executable_is_accepted_for_future_runner(tmp_path: Path) -> None:
    policy = SandboxedCommandExecutionPolicy()
    for executable in ("", "/bin/sh", "../sh", "sh; echo unsafe"):
        decision = policy.evaluate(workspace=_workspace(tmp_path), command=CommandRequest(executable=executable))
        assert decision.reason_code == "invalid_executable"


def test_minimal_environment_never_inherits_fake_secrets(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AVA_TEST_SECRET", "must-not-reach-command")
    monkeypatch.setenv("AVA_TEST_PROVIDER_TOKEN", "must-not-reach-command")
    decision = SandboxedCommandExecutionPolicy().evaluate(
        workspace=_workspace(tmp_path), command=CommandRequest(executable="pwd")
    )
    assert decision.environment == MINIMAL_COMMAND_ENVIRONMENT
    assert "AVA_TEST_SECRET" not in decision.environment
    assert "AVA_TEST_PROVIDER_TOKEN" not in decision.environment
    assert os.environ["AVA_TEST_SECRET"] == "must-not-reach-command"


def test_request_has_no_environment_or_timeout_override() -> None:
    fields = CommandRequest.__dataclass_fields__
    assert set(fields) == {"executable", "arguments", "working_directory"}
