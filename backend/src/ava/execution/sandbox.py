"""Runtime-neutral contracts for contained command execution."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SandboxResourceLimits:
    """Backend-owned limits for a single sandboxed command."""

    cpu_seconds: int = 30
    memory_bytes: int = 128 * 1024 * 1024
    process_count: int = 32
    output_bytes: int = 64 * 1024


@dataclass(frozen=True)
class SandboxedCommandRequest:
    """Internal structured command request; never a public API contract."""

    command_id: str
    executable: str
    arguments: tuple[str, ...]
    workspace_root: Path
    working_directory: Path
    workspace_writable: bool
    environment: dict[str, str]
    timeout_seconds: int
    network_allowed: bool
    limits: SandboxResourceLimits = field(default_factory=SandboxResourceLimits)


@dataclass(frozen=True)
class SandboxedCommandResult:
    """Normalized outcome from a sandbox runner."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False
    reason_code: str | None = None
    duration_seconds: float = 0.0


class SandboxedCommandRunnerPort(Protocol):
    """Replaceable AVA boundary for technically-contained command execution."""

    async def execute(self, request: SandboxedCommandRequest) -> SandboxedCommandResult: ...

    async def cancel(self, command_id: str) -> None: ...
