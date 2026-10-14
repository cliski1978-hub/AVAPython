"""Initial read-only tools run only through isolated test authorities."""

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest
from test_tool_policy import PolicyFixture

from ava.contracts.execution import ExecutionMode
from ava.contracts.tool_features import UpdateToolFeaturesRequest
from ava.contracts.tools import ToolCapability, ToolRequest
from ava.infrastructure.workspace_filesystem.linux import LinuxWorkspaceFilesystemAdapter
from ava.infrastructure.workspace_filesystem.windows import WindowsWorkspaceFilesystemAdapter
from ava.services.run_store import RunStore
from ava.services.tool_execution_service import InvocationReservationState, ToolExecutionService
from ava.tools.initial_tools import INITIAL_WORKSPACE_OPERATIONS, initial_workspace_tools
from ava.tools.workspace_filesystem import WorkspaceFilesystemSecurityPort
from ava.tools.workspace_read import WorkspaceReadExecutor


class _Reservations:
    durable = True

    def __init__(self) -> None:
        self.states: dict[str, InvocationReservationState] = {}

    def reserve(self, reservation):
        self.records = getattr(self, "records", {})
        self.records[reservation.invocation_id] = reservation
        self.states[reservation.invocation_id] = reservation.state
        return reservation

    def get(self, invocation_id):
        return self.records.get(invocation_id)

    def transition(self, invocation_id, *, expected_revision, state: InvocationReservationState, **metadata):
        from dataclasses import replace

        updated = replace(
            self.records[invocation_id],
            state=state,
            revision=expected_revision + 1,
            **{k: v for k, v in metadata.items() if v is not None},
        )
        self.records[invocation_id] = updated
        self.states[invocation_id] = state
        return updated

    def list_incomplete(self):
        return ()

    def list_for_run(self, run_id):
        return tuple(r for r in self.records.values() if r.run_id == run_id)


def _setup(
    root: Path,
    mode: ExecutionMode = ExecutionMode.AGENT,
    filesystem: WorkspaceFilesystemSecurityPort | None = None,
):
    fixture = PolicyFixture(root)
    for definition in initial_workspace_tools():
        fixture.registry.register(definition)
    operations = {**fixture.operations, **INITIAL_WORKSPACE_OPERATIONS}
    enabled = tuple(operations)
    fixture.features.update(
        UpdateToolFeaturesRequest(framework_enabled=True, enabled_tool_ids=enabled, expected_version=1)
    )
    authority = fixture.authority.grant
    assert authority is not None
    fixture.authority.grant = replace(
        authority,
        run_id="run-1",
        allowed_tool_ids=frozenset(operations),
    )
    policy = fixture.service()
    policy._operations = operations
    runs = RunStore()
    runs.create(
        "run-1",
        execution_mode=mode,
        owner_principal_ref="caller-1",
        owner_tenant_ref="tenant-1",
        execution_workspace_id="workspace-1",
    )
    executor = WorkspaceReadExecutor(filesystem or LinuxWorkspaceFilesystemAdapter())
    reservations = _Reservations()
    service = ToolExecutionService(
        runs=runs,
        registry=fixture.registry,
        features=fixture.features,
        policy=policy,
        authority=fixture.authority,
        executors={tool_id: executor for tool_id in INITIAL_WORKSPACE_OPERATIONS},
        reservations=reservations,
    )
    service._test_reservations = reservations
    return service


async def _execute(service, tool_id: str, path: str, **arguments):
    return await service.execute(
        ToolRequest(
            invocation_id=f"invocation-{tool_id.rsplit('.', 1)[-1]}",
            tool_id=tool_id,
            tool_version="1",
            arguments={"path": path, **arguments},
            execution_context_ref="context-1",
            run_id="run-1",
        )
    )


@pytest.mark.asyncio
async def test_list_read_metadata_empty_directory_and_bounded_pagination(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "a.txt").write_text("world", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    service = _setup(tmp_path)

    listed = await _execute(service, "workspace.list_files", ".", limit=1)
    assert listed.result is not None and listed.result.output is not None
    assert [item["name"] for item in listed.result.output["entries"]] == ["a.txt"]
    assert listed.result.output["next_cursor"] == "1"

    read = await _execute(service, "workspace.read_file", "a.txt")
    assert read.result is not None and read.result.output == {
        "content": "world",
        "encoding": "utf-8",
        "truncated": False,
        "size_bytes": 5,
    }
    truncated = await _execute(service, "workspace.read_file", "z.txt", max_bytes=2)
    assert truncated.result is not None and truncated.result.output is not None
    assert truncated.result.output["content"] == "he" and truncated.result.output["truncated"] is True
    (tmp_path / "unicode.txt").write_text("é", encoding="utf-8")
    unicode_truncated = await _execute(service, "workspace.read_file", "unicode.txt", max_bytes=1)
    assert unicode_truncated.result is not None and unicode_truncated.result.output is not None
    assert unicode_truncated.result.output["content"] == ""
    assert unicode_truncated.result.output["truncated"] is True
    info = await _execute(service, "workspace.file_info", "z.txt")
    assert info.result is not None and info.result.output is not None
    assert info.result.output["type"] == "file" and info.result.output["size_bytes"] == 5
    empty = await _execute(service, "workspace.list_files", "empty")
    assert empty.result is not None and empty.result.output == {"entries": []}


@pytest.mark.asyncio
async def test_invalid_traversal_absolute_paths_symlinks_and_utf8_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("must not be read", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    service = _setup(tmp_path)

    for invalid in ("../outside.txt", str(outside), ""):
        outcome = await _execute(service, "workspace.read_file", invalid)
        assert outcome.result is None or outcome.result.error is not None
    symlink = await _execute(service, "workspace.read_file", "link.txt")
    assert symlink.result is not None and symlink.result.error is not None
    assert symlink.result.error.error_code in {"security_validation_failed", "path_outside_workspace"}
    undecodable = await _execute(service, "workspace.read_file", "bad.txt")
    assert undecodable.result is not None and undecodable.result.error is not None
    assert undecodable.result.error.error_code == "decode_failure"
    outside.unlink()


@pytest.mark.asyncio
async def test_hard_links_and_non_regular_files_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    (tmp_path / "alias.txt").hardlink_to(source)
    try:
        os.mkfifo(tmp_path / "pipe")
    except NotImplementedError:
        pytest.skip("FIFO creation unsupported on this platform")
    service = _setup(tmp_path)
    for name in ("source.txt", "pipe"):
        outcome = await _execute(service, "workspace.read_file", name)
        assert outcome.result is not None and outcome.result.error is not None


@pytest.mark.asyncio
async def test_chat_mode_and_workspace_revision_drift_cannot_dispatch(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("content", encoding="utf-8")
    service = _setup(tmp_path, ExecutionMode.CHAT)
    outcome = await _execute(service, "workspace.read_file", "source.txt")
    assert outcome.disposition.value == "denied"

    service = _setup(tmp_path)
    grant = service._authority.grant
    service._authority.grant = replace(grant, workspace=replace(grant.workspace, configuration_revision=9))
    outcome = await _execute(service, "workspace.read_file", "source.txt")
    assert outcome.disposition.value == "denied"
    assert outcome.policy_reason == "workspace_changed"


@pytest.mark.asyncio
async def test_plan_mode_allows_only_the_normalized_read_tools(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("content", encoding="utf-8")
    service = _setup(tmp_path, ExecutionMode.PLAN)
    outcome = await _execute(service, "workspace.read_file", "source.txt")
    assert outcome.disposition.value == "executed"
    assert outcome.result is not None and outcome.result.output is not None
    assert outcome.result.output["content"] == "original"


@pytest.mark.asyncio
async def test_cancellation_during_execution_preserves_unknown_outcome(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("content", encoding="utf-8")
    service = _setup(tmp_path)
    request = ToolRequest(
        invocation_id="cancel-me",
        tool_id="workspace.read_file",
        tool_version="1",
        arguments={"path": "source.txt"},
        execution_context_ref="context-1",
        run_id="run-1",
    )
    task = asyncio.create_task(service.execute(request))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service._test_reservations.states["cancel-me"] == InvocationReservationState.INDETERMINATE


@pytest.mark.asyncio
async def test_nested_symlink_is_rejected_and_unsupported_host_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "source.txt").write_text("inside", encoding="utf-8")
    (tmp_path / "nested-link").symlink_to(subdir, target_is_directory=True)
    service = _setup(tmp_path)
    nested = await _execute(service, "workspace.read_file", "nested-link/source.txt")
    assert nested.disposition.value == "failed"
    assert nested.result is not None and nested.result.error is not None
    assert nested.result.error.error_code == "security_validation_failed"

    import ava.infrastructure.workspace_filesystem.linux as linux_adapter

    monkeypatch.setattr(linux_adapter.platform, "system", lambda: "Windows")
    unsupported = await _execute(service, "workspace.read_file", "source.txt")
    assert unsupported.result is not None and unsupported.result.error is not None
    assert unsupported.result.error.error_code == "secure_filesystem_unavailable"


@pytest.mark.asyncio
async def test_windows_adapter_fails_closed_without_native_security_certification(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("content", encoding="utf-8")
    service = _setup(tmp_path, filesystem=WindowsWorkspaceFilesystemAdapter())
    outcome = await _execute(service, "workspace.read_file", "source.txt")
    assert outcome.result is not None and outcome.result.error is not None
    assert outcome.result.error.error_code == "secure_filesystem_unavailable"


@pytest.mark.asyncio
async def test_symlink_retargeting_race_never_returns_the_temporary_external_target(tmp_path: Path) -> None:
    link = tmp_path / "target.txt"
    link.write_text("workspace", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("external-secret", encoding="utf-8")
    stop = Event()

    def retarget() -> None:
        while not stop.is_set():
            try:
                link.unlink(missing_ok=True)
                link.symlink_to(outside)
                link.unlink(missing_ok=True)
                link.write_text("workspace", encoding="utf-8")
            except OSError:
                continue

    worker = Thread(target=retarget)
    worker.start()
    service = _setup(tmp_path)
    try:
        for _ in range(20):
            outcome = await _execute(service, "workspace.read_file", "target.txt")
            output = outcome.result.output if outcome.result is not None else None
            assert not output or output.get("content") != "external-secret"
    finally:
        stop.set()
        worker.join(timeout=2)
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_directory_replacement_race_stays_beneath_the_pinned_workspace(tmp_path: Path) -> None:
    directory = tmp_path / "subdir"
    directory.mkdir()
    (directory / "source.txt").write_text("workspace", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-moved"
    outside.mkdir()
    (outside / "source.txt").write_text("outside", encoding="utf-8")
    stop = Event()

    def replace_directory() -> None:
        moved = tmp_path.parent / f"{tmp_path.name}-held"
        while not stop.is_set():
            try:
                if directory.exists() and not directory.is_symlink():
                    directory.rename(moved)
                    directory.symlink_to(outside, target_is_directory=True)
                directory.unlink(missing_ok=True)
                if moved.exists():
                    moved.rename(directory)
            except OSError:
                continue

    worker = Thread(target=replace_directory)
    worker.start()
    service = _setup(tmp_path)
    try:
        for _ in range(20):
            outcome = await _execute(service, "workspace.read_file", "subdir/source.txt")
            output = outcome.result.output if outcome.result is not None else None
            assert not output or output.get("content") != "outside"
    finally:
        stop.set()
        worker.join(timeout=2)
        moved = tmp_path.parent / f"{tmp_path.name}-held"
        if moved.exists():
            import shutil

            shutil.rmtree(moved)
        if directory.is_symlink():
            directory.unlink(missing_ok=True)
        outside_file = outside / "source.txt"
        outside_file.unlink(missing_ok=True)
        outside.rmdir()


def test_tool_contracts_expose_no_execution_host_or_resource_provider_selector() -> None:
    from ava.contracts.tools import ToolRequest

    assert "execution_host" not in ToolRequest.model_fields
    assert "resource_provider" not in ToolRequest.model_fields
    for definition in initial_workspace_tools():
        properties = definition.input_schema["properties"]
        assert isinstance(properties, dict)
        assert not {"execution_host", "resource_provider", "root_path"} & set(properties)
        assert definition.required_capabilities == (ToolCapability.FILE_READ,)


def test_ava_core_tool_modules_remain_platform_and_provider_neutral() -> None:
    import ast

    core_root = Path(__file__).parents[1] / "src" / "ava"
    core_modules = [
        core_root / "contracts" / "tools.py",
        core_root / "tools" / "initial_tools.py",
        core_root / "tools" / "registry.py",
        core_root / "tools" / "workspace_read.py",
        core_root / "tools" / "workspace_filesystem.py",
        core_root / "services" / "tool_execution_service.py",
        core_root / "services" / "tool_policy_service.py",
        core_root / "services" / "approval_service.py",
        core_root / "services" / "run_service.py",
    ]
    forbidden = {"ctypes", "winreg", "msvcrt", "fcntl", "boto3", "databricks", "azure"}
    for module in core_modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not imports & forbidden, f"platform/provider dependency found in {module.name}"


def test_host_adapter_is_selected_by_trusted_backend_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    import ava.infrastructure.composition as composition

    monkeypatch.setattr(composition.platform, "system", lambda: "Linux")
    linux_executor = composition.create_workspace_read_executor()
    assert isinstance(linux_executor._filesystem, LinuxWorkspaceFilesystemAdapter)
    monkeypatch.setattr(composition.platform, "system", lambda: "Windows")
    windows_executor = composition.create_workspace_read_executor()
    assert isinstance(windows_executor._filesystem, WindowsWorkspaceFilesystemAdapter)
