"""Bubblewrap-backed local command runner.

This adapter mounts the approved workspace at ``/workspace`` and creates new
user, PID, mount, IPC, UTS, cgroup, and network namespaces.  It intentionally
does not mount the host home, root, tmp, Docker socket, or AVA checkout.
"""

import asyncio
import logging
import os
import shutil
import signal
from collections.abc import Sequence
from pathlib import Path

from ava.execution.sandbox import (
    SandboxedCommandRequest,
    SandboxedCommandResult,
    SandboxedCommandRunnerPort,
)

logger = logging.getLogger(__name__)

_EXECUTABLES = {
    "cat": "/usr/bin/cat",
    "env": "/usr/bin/env",
    "ls": "/usr/bin/ls",
    "pwd": "/usr/bin/pwd",
    "python": "/usr/bin/python3.11",
    "python3": "/usr/bin/python3.11",
    "python3.11": "/usr/bin/python3.11",
    "sleep": "/usr/bin/sleep",
}

_LIMITED_ENTRYPOINT = (
    "import os,resource,sys; "
    "cpu,memory,pids=map(int,sys.argv[1:4]); "
    "resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu)); "
    "resource.setrlimit(resource.RLIMIT_AS,(memory,memory)); "
    "resource.setrlimit(resource.RLIMIT_NPROC,(pids,pids)); "
    "os.execv(sys.argv[4],sys.argv[4:])"
)


class BubblewrapSandboxedCommandRunner(SandboxedCommandRunnerPort):
    """Run a small, allowlisted command in a Bubblewrap mount namespace."""

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or shutil.which("bwrap")
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled: set[str] = set()

    @property
    def available(self) -> bool:
        return self._binary is not None

    async def execute(self, request: SandboxedCommandRequest) -> SandboxedCommandResult:
        error = self._validate(request)
        if error is not None:
            return SandboxedCommandResult(None, "", "", reason_code=error)
        assert self._binary is not None
        command = self._build_command(request)
        started = asyncio.get_running_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={},
                start_new_session=True,
            )
        except OSError:
            return SandboxedCommandResult(None, "", "", reason_code="sandbox_start_failed")
        self._processes[request.command_id] = process
        try:
            stdout_task = asyncio.create_task(_read_capped(process.stdout, request.limits.output_bytes))
            stderr_task = asyncio.create_task(_read_capped(process.stderr, request.limits.output_bytes))
            try:
                await asyncio.wait_for(process.wait(), timeout=request.timeout_seconds)
            except TimeoutError:
                await self._terminate(process)
                stdout, stdout_truncated = await stdout_task
                stderr, stderr_truncated = await stderr_task
                return SandboxedCommandResult(
                    process.returncode, stdout, stderr, timed_out=True,
                    output_truncated=stdout_truncated or stderr_truncated, reason_code="timeout",
                    duration_seconds=asyncio.get_running_loop().time() - started,
                )
            stdout, stdout_truncated = await stdout_task
            stderr, stderr_truncated = await stderr_task
            cancelled = request.command_id in self._cancelled
            reason = "cancelled" if cancelled else None
            if not cancelled and stderr.startswith("bwrap:"):
                logger.warning("Sandbox bootstrap failed: %s", stderr)
                stdout, stderr, reason = "", "", "sandbox_start_failed"
            elif not cancelled and process.returncode == -signal.SIGXCPU:
                reason = "sandbox_resource_limit"
            return SandboxedCommandResult(
                process.returncode, stdout, stderr,
                cancelled=cancelled,
                output_truncated=stdout_truncated or stderr_truncated,
                reason_code=reason,
                duration_seconds=asyncio.get_running_loop().time() - started,
            )
        except asyncio.CancelledError:
            await self._terminate(process)
            await asyncio.gather(stdout_task, stderr_task)
            return SandboxedCommandResult(
                None, "", "", cancelled=True, reason_code="cancelled",
                duration_seconds=asyncio.get_running_loop().time() - started,
            )
        finally:
            self._processes.pop(request.command_id, None)
            self._cancelled.discard(request.command_id)

    async def cancel(self, command_id: str) -> None:
        process = self._processes.get(command_id)
        if process is not None:
            self._cancelled.add(command_id)
            await self._terminate(process)

    def _validate(self, request: SandboxedCommandRequest) -> str | None:
        if self._binary is None:
            return "sandbox_unavailable"
        if request.environment != {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}:
            return "environment_not_allowed"
        if request.timeout_seconds <= 0 or any(value <= 0 for value in (
            request.limits.cpu_seconds, request.limits.memory_bytes,
            request.limits.process_count, request.limits.output_bytes,
        )):
            return "invalid_resource_limits"
        if request.network_allowed:
            return "network_policy_unsupported"
        if request.executable not in _EXECUTABLES:
            return "executable_not_allowed"
        try:
            root = request.workspace_root.resolve(strict=True)
            directory = request.working_directory.resolve(strict=True)
        except OSError:
            return "workspace_unavailable"
        if not root.is_dir() or not directory.is_dir() or (directory != root and root not in directory.parents):
            return "working_directory_outside_workspace"
        return None

    def _build_command(self, request: SandboxedCommandRequest) -> Sequence[str]:
        root = request.workspace_root.resolve()
        directory = request.working_directory.resolve()
        relative_directory = directory.relative_to(root)
        command = [
            self._binary or "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--dir", "/workspace",
            "--dir", "/tmp/ava-home",
        ]
        if request.workspace_writable:
            command.extend(("--bind", str(root), "/workspace"))
        else:
            command.extend(("--ro-bind", str(root), "/workspace"))
        for key, value in request.environment.items():
            command.extend(("--setenv", key, value))
        command.extend(("--setenv", "HOME", "/tmp/ava-home"))
        command.extend(("--setenv", "TMPDIR", "/tmp"))
        command.extend(("--chdir", str(Path("/workspace") / relative_directory)))
        command.extend((
            "/usr/bin/python3.11",
            "-c",
            _LIMITED_ENTRYPOINT,
            str(request.limits.cpu_seconds),
            str(request.limits.memory_bytes),
            str(request.limits.process_count),
            _EXECUTABLES[request.executable],
        ))
        command.extend(request.arguments)
        return command

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()


async def _read_capped(
    stream: asyncio.StreamReader | None, limit: int
) -> tuple[str, bool]:
    if stream is None:
        return "", False
    chunks: list[bytes] = []
    remaining = limit
    truncated = False
    while chunk := await stream.read(4096):
        prior_remaining = remaining
        if remaining:
            chunks.append(chunk[:remaining])
            remaining -= len(chunk[:remaining])
        if len(chunk) > prior_remaining:
            truncated = True
    return b"".join(chunks).decode("utf-8", errors="replace"), truncated
