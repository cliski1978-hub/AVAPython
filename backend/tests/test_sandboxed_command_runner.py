"""Step 34B Bubblewrap containment tests.

Every command runs only in a temporary workspace through AVA's structured
runner; no test touches the repository or invokes a host shell.
"""

import asyncio
import socket
from pathlib import Path

import pytest

from ava.execution.command_policy import CommandRequest, SandboxedCommandExecutionPolicy
from ava.execution.sandbox import SandboxedCommandRequest, SandboxResourceLimits
from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions


@pytest.fixture()
def runner() -> BubblewrapSandboxedCommandRunner:
    candidate = BubblewrapSandboxedCommandRunner()
    if not candidate.available:
        pytest.skip("Bubblewrap is unavailable")
    return candidate


def _request(
    root: Path,
    *,
    command_id: str = "test-command",
    executable: str = "pwd",
    arguments: tuple[str, ...] = (),
    writable: bool = True,
    timeout: int = 5,
    limits: SandboxResourceLimits | None = None,
) -> SandboxedCommandRequest:
    return SandboxedCommandRequest(
        command_id=command_id,
        executable=executable,
        arguments=arguments,
        workspace_root=root,
        working_directory=root,
        workspace_writable=writable,
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout_seconds=timeout,
        network_allowed=False,
        limits=limits or SandboxResourceLimits(),
    )


def test_policy_can_create_runner_request_only_when_runner_is_available(tmp_path: Path) -> None:
    workspace = RuntimeWorkspaceBinding(
        workspace_id="sandbox-test", kind=WorkspaceKind.LOCAL, local_path=tmp_path,
        permissions=WorkspacePermissions(read=True, write=True, shell=True),
    )
    policy = SandboxedCommandExecutionPolicy(runner_available=True)
    command = CommandRequest(executable="pwd")
    decision = policy.evaluate(workspace=workspace, command=command)
    request = policy.to_sandboxed_request(
        command_id="policy", workspace=workspace, command=command, decision=decision
    )
    assert decision.allowed
    assert request.workspace_root == tmp_path
    assert request.network_allowed is False


def test_pwd_and_read_inside_workspace(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("inside only\n", encoding="utf-8")
    pwd = asyncio.run(runner.execute(_request(tmp_path)))
    assert pwd.exit_code == 0
    assert pwd.stdout.strip() == "/workspace"
    read = asyncio.run(runner.execute(_request(tmp_path, executable="cat", arguments=("sample.txt",))))
    assert read.exit_code == 0
    assert read.stdout == "inside only\n"


def test_read_write_and_read_only_mounts(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    code = "from pathlib import Path; Path('created.txt').write_text('created')"
    writable = asyncio.run(runner.execute(_request(tmp_path, executable="python", arguments=("-c", code))))
    assert writable.exit_code == 0, writable.stderr
    assert (tmp_path / "created.txt").read_text() == "created"
    read_only_code = "from pathlib import Path; Path('readonly.txt').write_text('denied')"
    read_only = asyncio.run(runner.execute(_request(
        tmp_path, command_id="readonly", executable="python", arguments=("-c", read_only_code), writable=False
    )))
    assert read_only.exit_code != 0
    assert not (tmp_path / "readonly.txt").exists()


def test_outside_host_paths_and_symlink_escape_are_inaccessible(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside secret", encoding="utf-8")
    direct = asyncio.run(runner.execute(_request(tmp_path, executable="cat", arguments=(str(outside),))))
    assert direct.exit_code != 0
    assert "outside secret" not in direct.stdout
    link = tmp_path / "escape-link"
    link.symlink_to(outside)
    through_link = asyncio.run(runner.execute(_request(tmp_path, executable="cat", arguments=("escape-link",))))
    assert through_link.exit_code != 0
    assert "outside secret" not in through_link.stdout


def test_home_and_backend_secrets_are_not_exposed(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AVA_TEST_SECRET", "do-not-leak")
    monkeypatch.setenv("AVA_TEST_PROVIDER_TOKEN", "do-not-leak")
    code = (
        "import os; print(os.getenv('AVA_TEST_SECRET')); "
        "print(os.getenv('AVA_TEST_PROVIDER_TOKEN')); print(os.getenv('HOME'))"
    )
    result = asyncio.run(runner.execute(_request(tmp_path, executable="python", arguments=("-c", code))))
    assert result.exit_code == 0
    assert "do-not-leak" not in result.stdout
    assert result.stdout.splitlines() == ["None", "None", "/tmp/ava-home"]


def test_network_namespace_blocks_host_loopback(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    try:
        code = f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=1)"
        result = asyncio.run(runner.execute(_request(tmp_path, executable="python", arguments=("-c", code))))
    finally:
        server.close()
    assert result.reason_code is None
    assert result.exit_code != 0
    assert "ConnectionRefusedError" in result.stderr


def test_timeout_cancellation_and_child_process_cleanup(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path
) -> None:
    timeout = asyncio.run(runner.execute(_request(
        tmp_path, command_id="timeout", executable="sleep", arguments=("10",), timeout=1
    )))
    assert timeout.timed_out
    assert timeout.reason_code == "timeout"

    async def scenario() -> None:
        task = asyncio.create_task(runner.execute(_request(
            tmp_path, command_id="cancel", executable="sleep", arguments=("10",), timeout=10
        )))
        await asyncio.sleep(0.2)
        await runner.cancel("cancel")
        result = await task
        assert result.cancelled
        assert result.reason_code == "cancelled"

    asyncio.run(scenario())

    child_marker = tmp_path / "child-survived.txt"
    child_program = "import time; time.sleep(2); open('child-survived.txt','w').write('bad')"
    child = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_program!r}]); "
        "time.sleep(10)"
    )
    child_result = asyncio.run(runner.execute(_request(
        tmp_path, command_id="child", executable="python", arguments=("-c", child), timeout=1
    )))
    assert child_result.timed_out
    # Bubblewrap's PID namespace ends with the parent and the runner also
    # terminates the outer process group, so the child cannot write later.
    asyncio.run(asyncio.sleep(2.2))
    assert not child_marker.exists()


def test_memory_process_and_output_limits(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    constrained = SandboxResourceLimits(memory_bytes=96 * 1024 * 1024, process_count=12, output_bytes=1024)
    memory = asyncio.run(runner.execute(_request(
        tmp_path, command_id="memory", executable="python", arguments=("-c", "bytearray(160 * 1024 * 1024)"),
        limits=constrained,
    )))
    assert memory.reason_code is None
    assert memory.exit_code != 0
    assert "MemoryError" in memory.stderr
    output = asyncio.run(runner.execute(_request(
        tmp_path, command_id="output", executable="python", arguments=("-c", "print('x' * 4096)"),
        limits=constrained,
    )))
    assert output.output_truncated
    assert len(output.stdout.encode()) == constrained.output_bytes
    # The bounded loop leaves children sleeping only until the runner timeout;
    # RLIMIT_NPROC makes the child creation fail rather than permitting a fork bomb.
    forks = """import os
import time
n = 0
for _ in range(64):
    try:
        pid = os.fork()
    except OSError:
        print(n)
        break
    if pid == 0:
        time.sleep(10)
        os._exit(0)
    n += 1
"""
    processes = asyncio.run(runner.execute(_request(
        tmp_path, command_id="processes", executable="python", arguments=("-c", forks), timeout=2, limits=constrained
    )))
    assert (
        processes.timed_out
        or processes.exit_code != 0
        or (processes.stdout.strip().isdigit() and int(processes.stdout.strip()) <= constrained.process_count)
    )


def test_network_true_and_unknown_executables_are_rejected(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path
) -> None:
    network_request = _request(tmp_path)
    network_request = SandboxedCommandRequest(**{**network_request.__dict__, "network_allowed": True})
    assert asyncio.run(runner.execute(network_request)).reason_code == "network_policy_unsupported"
    unknown = _request(tmp_path, executable="apt")
    assert asyncio.run(runner.execute(unknown)).reason_code == "executable_not_allowed"


def test_private_temp_and_environment_sentinel(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setenv("AVA_FAKE_SECRET_DO_NOT_LEAK", "sentinel-secret")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/fake-agent")
    with tempfile.NamedTemporaryFile(prefix="ava-private-temp-") as host_temp:
        code = (
            "import os,pathlib; "
            "print(os.environ.get('AVA_FAKE_SECRET_DO_NOT_LEAK')); "
            "print(os.environ.get('SSH_AUTH_SOCK')); "
            "print(os.environ['HOME']); print(os.environ['TMPDIR']); "
            f"print(pathlib.Path({host_temp.name!r}).exists())"
        )
        result = asyncio.run(runner.execute(_request(tmp_path, executable="python", arguments=("-c", code))))
    assert result.exit_code == 0, result.reason_code
    assert result.stdout.splitlines() == ["None", "None", "/tmp/ava-home", "/tmp", "False"]


def test_host_process_is_absent_and_cannot_be_signalled(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path,
) -> None:
    import subprocess
    import sys

    # Only a synthetic process owned by this test is targeted. A PID above the
    # tiny sandbox namespace avoids accidental aliasing with its init process.
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"]) as host:
        try:
            code = (
                "import os,pathlib; "
                f"assert not pathlib.Path('/proc/{host.pid}').exists(); "
                f"os.kill({host.pid}, 0)"
            )
            result = asyncio.run(runner.execute(_request(tmp_path, executable="python", arguments=("-c", code))))
            assert result.exit_code != 0
            assert "ProcessLookupError" in result.stderr
            assert host.poll() is None
        finally:
            host.terminate()
            host.wait(timeout=3)


def test_cpu_limit_is_installed_without_stress(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    result = asyncio.run(runner.execute(_request(
        tmp_path, executable="python",
        arguments=("-c", "import resource; print(resource.getrlimit(resource.RLIMIT_CPU))"),
        limits=SandboxResourceLimits(cpu_seconds=2),
    )))
    assert result.exit_code == 0
    assert result.stdout.strip() == "(2, 2)"


def test_unapproved_environment_is_rejected(runner: BubblewrapSandboxedCommandRunner, tmp_path: Path) -> None:
    from dataclasses import replace

    request = replace(_request(tmp_path), environment={"AVA_FAKE_SECRET_DO_NOT_LEAK": "sentinel"})
    result = asyncio.run(runner.execute(request))
    assert result.reason_code == "environment_not_allowed"
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout-tree", "cancel-tree"])
def test_owned_parent_and_child_exit(
    runner: BubblewrapSandboxedCommandRunner, tmp_path: Path, cancel: bool,
) -> None:
    child_code = "import time; open('child-ready','w').write('ready'); time.sleep(10)"
    code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(10)"

    def owned_tree(pid: int) -> set[int]:
        children_file = Path(f"/proc/{pid}/task/{pid}/children")
        children = [int(value) for value in children_file.read_text().split()]
        result = {pid}
        for child in children:
            result.update(owned_tree(child))
        return result

    async def scenario() -> None:
        task = asyncio.create_task(runner.execute(_request(
            tmp_path, command_id="owned-tree", executable="python", arguments=("-c", code), timeout=2,
        )))
        try:
            for _ in range(100):
                if (tmp_path / "child-ready").exists():
                    break
                await asyncio.sleep(0.01)
            assert (tmp_path / "child-ready").exists()
            parent = runner._processes["owned-tree"]
            pids = owned_tree(parent.pid)
            assert len(pids) >= 3  # outer bwrap, command parent, command child
            if cancel:
                await runner.cancel("owned-tree")
            result = await asyncio.wait_for(task, 4)
            assert result.cancelled if cancel else result.timed_out
            for _ in range(100):
                if all(not Path(f"/proc/{pid}").exists() for pid in pids):
                    break
                await asyncio.sleep(0.01)
            assert all(not Path(f"/proc/{pid}").exists() for pid in pids)
        finally:
            if not task.done():
                task.cancel()
                await task

    asyncio.run(scenario())
