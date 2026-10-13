"""The same filesystem contract runs against the native adapter on each OS."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from test_tool_policy import PolicyFixture

from ava.contracts.execution import ExecutionMode
from ava.contracts.tool_features import UpdateToolFeaturesRequest
from ava.contracts.tools import ToolRequest
from ava.infrastructure.workspace_filesystem.linux import LinuxWorkspaceFilesystemAdapter
from ava.infrastructure.workspace_filesystem.windows import WindowsWorkspaceFilesystemAdapter
from ava.services.run_store import RunStore
from ava.services.tool_execution_service import ToolExecutionService
from ava.tools.initial_tools import INITIAL_WORKSPACE_OPERATIONS, initial_workspace_tools
from ava.tools.workspace_read import WorkspaceReadExecutor


def _native_adapter():
    return WindowsWorkspaceFilesystemAdapter() if os.name == "nt" else LinuxWorkspaceFilesystemAdapter()


def _service(root: Path) -> ToolExecutionService:
    fixture = PolicyFixture(root)
    for definition in initial_workspace_tools():
        fixture.registry.register(definition)
    operations = {**fixture.operations, **INITIAL_WORKSPACE_OPERATIONS}
    fixture.features.update(
        UpdateToolFeaturesRequest(framework_enabled=True, enabled_tool_ids=tuple(operations), expected_version=1)
    )
    assert fixture.authority.grant is not None
    fixture.authority.grant = replace(
        fixture.authority.grant,
        run_id="run-1",
        allowed_tool_ids=frozenset(operations),
    )
    policy = fixture.service()
    policy._operations = operations
    runs = RunStore()
    runs.create("run-1", execution_mode=ExecutionMode.AGENT)
    executor = WorkspaceReadExecutor(_native_adapter())
    reservations = _Reservations()
    return ToolExecutionService(
        runs=runs,
        registry=fixture.registry,
        features=fixture.features,
        policy=policy,
        authority=fixture.authority,
        executors={tool_id: executor for tool_id in INITIAL_WORKSPACE_OPERATIONS},
        reservations=reservations,
    )


class _Reservations:
    durable = True

    def reserve(self, invocation_id, binding):
        return True

    def transition(self, invocation_id, state):
        return None


async def _invoke(service: ToolExecutionService, tool_id: str, path: str, **arguments):
    return await service.execute(
        ToolRequest(
            invocation_id=f"contract-{tool_id.rsplit('.', 1)[-1]}",
            tool_id=tool_id,
            tool_version="1",
            arguments={"path": path, **arguments},
            execution_context_ref="context-1",
            run_id="run-1",
        )
    )


@pytest.mark.asyncio
async def test_native_filesystem_shared_read_list_info_bounded_and_deterministic(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "A.txt").write_text("world", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    service = _service(tmp_path)

    listing = await _invoke(service, "workspace.list_files", ".", limit=1)
    assert listing.result is not None and listing.result.output is not None
    assert listing.result.output["entries"][0]["name"] == "A.txt"
    assert listing.result.output["next_cursor"] == "1"
    read = await _invoke(service, "workspace.read_file", "A.txt")
    assert read.result is not None and read.result.output == {
        "content": "world",
        "encoding": "utf-8",
        "truncated": False,
        "size_bytes": 5,
    }
    truncated = await _invoke(service, "workspace.read_file", "z.txt", max_bytes=2)
    assert truncated.result is not None and truncated.result.output is not None
    assert truncated.result.output["content"] == "he" and truncated.result.output["truncated"] is True
    info = await _invoke(service, "workspace.file_info", "z.txt")
    assert info.result is not None and info.result.output is not None
    assert info.result.output["type"] == "file" and info.result.output["size_bytes"] == 5
    empty = await _invoke(service, "workspace.list_files", "empty")
    assert empty.result is not None and empty.result.output == {"entries": []}


@pytest.mark.asyncio
async def test_native_filesystem_shared_path_and_argument_rejections(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    service = _service(tmp_path)
    for invalid in ("../outside.txt", "", "a//b", ".\\safe.txt"):
        outcome = await _invoke(service, "workspace.read_file", invalid)
        assert outcome.result is None or outcome.result.error is not None
    for invocation in (
        await _invoke(service, "workspace.read_file", "safe.txt", max_bytes=0),
        await _invoke(service, "workspace.list_files", ".", limit=101),
        await _invoke(service, "workspace.read_file", "missing.txt"),
    ):
        assert invocation.result is not None and invocation.result.error is not None


@pytest.mark.asyncio
async def test_native_filesystem_shared_rejects_hard_links_and_file_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "linked.txt").hardlink_to(outside)
    try:
        (tmp_path / "symbolic.txt").symlink_to(outside)
    except OSError as exc:
        if os.name == "nt":
            pytest.fail(f"Windows runner lacks required file-symlink capability: {exc}")
        raise
    service = _service(tmp_path)
    for name in ("linked.txt", "symbolic.txt"):
        outcome = await _invoke(service, "workspace.read_file", name)
        assert outcome.result is not None and outcome.result.error is not None
    outside.unlink()
