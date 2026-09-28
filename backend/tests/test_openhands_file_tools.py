"""Step 33: deterministic tests for contained OpenHands file access.

These tests exercise the real installed OpenHands file editor (base + path
containment + read-only gate) against temporary directories, plus the policy,
registry resolution, agent tool-list wiring, and fail-safe runtime paths.
"""

import asyncio
import builtins
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openhands.tools.file_editor")

from openhands.sdk import LLM, Agent, Conversation, Tool  # noqa: E402
from openhands.sdk.tool.registry import resolve_tool  # noqa: E402
from openhands.tools.file_editor.definition import FileEditorAction  # noqa: E402

from ava.contracts.models import ModelCapabilities, ModelInfo  # noqa: E402
from ava.contracts.requests import RunRequest  # noqa: E402
from ava.contracts.responses import RunStatus  # noqa: E402
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo  # noqa: E402
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.models.bindings import RuntimeModelBinding  # noqa: E402
from ava.runtimes.adapters.openhands.file_policy import (  # noqa: E402
    FILE_EDITOR_TOOL_NAME,
    build_openhands_tools,
)
from ava.runtimes.adapters.openhands.file_tools import (  # noqa: E402
    AvaFileEditorTool,
    ContainedFileEditorExecutor,
)
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime  # noqa: E402
from ava.runtimes.contracts import RuntimeRunResult  # noqa: E402
from ava.workspaces.contracts import (  # noqa: E402
    RuntimeWorkspaceBinding,
    WorkspaceKind,
    WorkspacePermissions,
)

FILE_TEXT = "AVA file tool OK\n"
OUTSIDE = "MUST NOT TOUCH\n"


def _payload(
    *, read: bool, write: bool, local_path: str | None = "w-root", shell: bool = True
) -> RuntimeWorkspaceBinding:
    return RuntimeWorkspaceBinding(
        workspace_id="w1",
        kind=WorkspaceKind.LOCAL,
        local_path=Path(local_path) if local_path is not None else None,
        permissions=WorkspacePermissions(read=read, write=write, shell=shell, network=True),
    )


def _text(observation: Any) -> str:
    parts = [c.text for c in observation.content if hasattr(c, "text")]
    return "".join(parts)


def _dispatch(executor: ContainedFileEditorExecutor, **kwargs: Any) -> Any:
    return executor(FileEditorAction(**kwargs))


# ============================================================
# Policy: deterministic tool activation
# ============================================================


def test_policy_activates_no_tools_without_workspace() -> None:
    assert build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=None) == []
    assert build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True, local_path=None)) == []


def test_policy_activates_no_tools_without_read_permission() -> None:
    assert build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=False, write=False)) == []
    assert build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=False, write=True)) == []


def test_policy_activates_read_only_file_editor() -> None:
    tools = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=False))
    assert tools == [Tool(name=FILE_EDITOR_TOOL_NAME, params={"read_only": True})]
    assert tools[0].name == FILE_EDITOR_TOOL_NAME


def test_policy_activates_read_write_file_editor() -> None:
    tools = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True))
    assert tools == [Tool(name=FILE_EDITOR_TOOL_NAME)]
    assert tools[0].name == FILE_EDITOR_TOOL_NAME
    assert tools[0].params == {}


def test_policy_ignores_shell_and_network_permissions() -> None:
    tools = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True))
    assert [tool.name for tool in tools] == [FILE_EDITOR_TOOL_NAME]


def test_controlled_terminal_requires_shell_permission_and_composed_dependencies(tmp_path: Path) -> None:
    from ava.execution.command_policy import SandboxedCommandExecutionPolicy
    from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner
    from ava.runtimes.adapters.openhands.controlled_terminal import AVA_TERMINAL_TOOL_NAME

    policy = SandboxedCommandExecutionPolicy(runner_available=True)
    runner = BubblewrapSandboxedCommandRunner()
    no_shell = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True, local_path=str(tmp_path), shell=False),
        command_policy=policy,
        command_runner=runner,
    )
    assert [tool.name for tool in no_shell] == [FILE_EDITOR_TOOL_NAME]
    shell = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=RuntimeWorkspaceBinding(
            workspace_id="shell", kind=WorkspaceKind.LOCAL, local_path=tmp_path,
            permissions=WorkspacePermissions(read=True, write=True, shell=True, network=False),
        ),
        command_policy=policy,
        command_runner=runner,
    )
    assert [tool.name for tool in shell] == [FILE_EDITOR_TOOL_NAME, AVA_TERMINAL_TOOL_NAME]
    no_read = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=False, write=True, local_path=str(tmp_path), shell=True),
        command_policy=policy,
        command_runner=runner,
    )
    assert no_read == []


# ============================================================
# Containment: read/write editor
# ============================================================


@pytest.fixture()
def rw_executor(tmp_path: Path) -> ContainedFileEditorExecutor:
    return ContainedFileEditorExecutor(workspace_root=str(tmp_path), read_only=False)


@pytest.fixture()
def read_only_executor(tmp_path: Path) -> ContainedFileEditorExecutor:
    return ContainedFileEditorExecutor(workspace_root=str(tmp_path), read_only=True)


def test_create_and_view_inside_workspace(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    target = tmp_path / "notes.txt"
    created = _dispatch(rw_executor, command="create", path=str(target), file_text=FILE_TEXT)
    assert not created.is_error, _text(created)
    assert target.read_text(encoding="utf-8") == FILE_TEXT
    viewed = _dispatch(rw_executor, command="view", path=str(target))
    assert not viewed.is_error
    assert "AVA file tool OK" in _text(viewed)


def test_str_replace_and_undo_inside_workspace(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("alpha beta gamma\n", encoding="utf-8")
    replaced = _dispatch(
        rw_executor, command="str_replace", path=str(target), old_str="beta", new_str="BETA"
    )
    assert not replaced.is_error, _text(replaced)
    assert "alpha BETA gamma" in target.read_text(encoding="utf-8")
    undone = _dispatch(rw_executor, command="undo_edit", path=str(target))
    assert not undone.is_error, _text(undone)
    assert "alpha beta gamma" in target.read_text(encoding="utf-8")


def test_insert_inside_workspace(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("one\n", encoding="utf-8")
    inserted = _dispatch(rw_executor, command="insert", path=str(target), insert_line=1, new_str="two")
    assert not inserted.is_error, _text(inserted)
    assert "one\ntwo" in target.read_text(encoding="utf-8")


def test_nested_paths_inside_workspace(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    nested = tmp_path / "b" / "c"
    nested.mkdir(parents=True)
    created = _dispatch(rw_executor, command="create", path=str(nested / "deep.txt"), file_text=FILE_TEXT)
    assert not created.is_error, _text(created)
    assert (nested / "deep.txt").read_text(encoding="utf-8") == FILE_TEXT


def test_absolute_escape_is_denied(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text(OUTSIDE, encoding="utf-8")
    viewed = _dispatch(rw_executor, command="view", path=str(outside))
    assert viewed.is_error
    assert "outside the approved AVA workspace" in _text(viewed)
    created = _dispatch(rw_executor, command="create", path=str(tmp_path.parent / "created.txt"), file_text=FILE_TEXT)
    assert created.is_error
    assert "outside the approved AVA workspace" in _text(created)
    assert not (tmp_path.parent / "created.txt").exists()


def test_dotdot_escape_is_denied(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    before = list(tmp_path.parent.iterdir())
    attempt = _dispatch(rw_executor, command="view", path=str(tmp_path / ".." / "runaway.txt"))
    assert attempt.is_error
    assert "outside the approved AVA workspace" in _text(attempt)
    mutation = _dispatch(
        rw_executor, command="create", path=str(tmp_path / "../runaway.txt"), file_text=FILE_TEXT
    )
    assert mutation.is_error
    after = sorted(p.name for p in tmp_path.parent.iterdir())
    assert after == sorted(p.name for p in before)


def test_directory_listing_filters_symlink_escape(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    outside_dir = tmp_path.parent / "outside-dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "link-out").symlink_to(outside_dir, target_is_directory=True)
    listing = _dispatch(rw_executor, command="view", path=str(tmp_path))
    assert not listing.is_error, _text(listing)
    text = _text(listing)
    assert "secret.txt" not in text


@pytest.mark.skipif(os.name == "nt", reason="symlink privileges unavailable on Windows")
def test_file_symlink_escape_is_denied(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    outside = tmp_path.parent / "outside-target.txt"
    outside.write_text(OUTSIDE, encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    viewed = _dispatch(rw_executor, command="view", path=str(link))
    assert viewed.is_error, _text(viewed)
    assert "outside the approved AVA workspace" in _text(viewed)
    wrote = _dispatch(
        rw_executor, command="str_replace", path=str(link), old_str="MUST NOT", new_str="CHANGED"
    )
    assert wrote.is_error
    assert outside.read_text(encoding="utf-8") == OUTSIDE


@pytest.mark.skipif(os.name == "nt", reason="symlink privileges unavailable on Windows")
def test_directory_symlink_create_escape_is_denied(tmp_path: Path, rw_executor: ContainedFileEditorExecutor) -> None:
    outside_dir = tmp_path.parent / "outside-dir"
    outside_dir.mkdir(exist_ok=True)
    link = tmp_path / "linkdir"
    link.symlink_to(outside_dir, target_is_directory=True)
    attempt = _dispatch(
        rw_executor, command="create", path=str(link / "evil.txt"), file_text=FILE_TEXT
    )
    assert attempt.is_error, _text(attempt)
    assert not (outside_dir / "evil.txt").exists()


def test_read_only_workspace_rejects_all_mutations(
    tmp_path: Path, read_only_executor: ContainedFileEditorExecutor
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("original\n", encoding="utf-8")
    for attempt in (
        _dispatch(read_only_executor, command="create", path=str(target), file_text=FILE_TEXT),
        _dispatch(read_only_executor, command="str_replace", path=str(target), old_str="original", new_str="X"),
        _dispatch(read_only_executor, command="insert", path=str(target), insert_line=0, new_str="X"),
        _dispatch(read_only_executor, command="undo_edit", path=str(target)),
    ):
        assert attempt.is_error, _text(attempt)
        assert "read-only" in _text(attempt)
    assert target.read_text(encoding="utf-8") == "original\n"


def test_read_only_workspace_allows_view(tmp_path: Path, read_only_executor: ContainedFileEditorExecutor) -> None:
    target = tmp_path / "notes.txt"
    target.write_text(FILE_TEXT, encoding="utf-8")
    viewed = _dispatch(read_only_executor, command="view", path=str(target))
    assert not viewed.is_error, _text(viewed)
    assert "AVA file tool OK" in _text(viewed)


def test_create_outside_read_only_is_denied_as_outside(
    tmp_path: Path, read_only_executor: ContainedFileEditorExecutor
) -> None:
    attempt = _dispatch(
        read_only_executor, command="create", path=str(tmp_path.parent / "x.txt"), file_text=FILE_TEXT
    )
    assert attempt.is_error
    assert "outside the approved AVA workspace" in _text(attempt)


def test_contained_editor_requires_root() -> None:
    from ava.runtimes.adapters.openhands.file_tools import ContainedFileEditor

    with pytest.raises(ValueError, match="approved workspace root"):
        ContainedFileEditor(workspace_root=None)


# ============================================================
# Registry resolution: the contained editor answers file_editor
# ============================================================


def _fake_state(workspace_root: str) -> Any:
    class _NoVision:
        def vision_is_active(self) -> bool:
            return False

    return SimpleNamespace(
        workspace=SimpleNamespace(working_dir=workspace_root),
        agent=SimpleNamespace(llm=_NoVision()),
    )


def test_registered_file_editor_resolves_to_contained_tool(tmp_path: Path) -> None:
    state = _fake_state(str(tmp_path))
    resolved = resolve_tool(Tool(name=FILE_EDITOR_TOOL_NAME), state)
    assert len(resolved) == 1
    tool = resolved[0]
    assert isinstance(tool, AvaFileEditorTool)
    assert tool.name == FILE_EDITOR_TOOL_NAME
    assert isinstance(tool.executor, ContainedFileEditorExecutor)
    assert tool.executor.editor._root == Path(tmp_path).resolve()  # noqa: SLF001


def test_registered_read_only_spec_applies_contained_read_only(tmp_path: Path) -> None:
    state = _fake_state(str(tmp_path))
    resolved = resolve_tool(Tool(name=FILE_EDITOR_TOOL_NAME, params={"read_only": True}), state)
    assert len(resolved) == 1
    tool = resolved[0]
    assert isinstance(tool.executor, ContainedFileEditorExecutor)
    assert tool.executor.editor._read_only is True
    target = tmp_path / "notes.txt"
    target.write_text("keep\n", encoding="utf-8")
    observation = tool.executor(FileEditorAction(command="create", path=str(target), file_text=FILE_TEXT))
    assert observation.is_error
    assert "read-only" in _text(observation)
    assert target.read_text(encoding="utf-8") == "keep\n"


def test_controlled_terminal_resolves_and_uses_ava_runner(tmp_path: Path) -> None:
    from ava.execution.command_policy import SandboxedCommandExecutionPolicy
    from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner
    from ava.runtimes.adapters.openhands.controlled_terminal import (
        AVA_TERMINAL_TOOL_NAME,
        AvaTerminalAction,
        AvaTerminalExecutor,
    )

    runner = BubblewrapSandboxedCommandRunner()
    if not runner.available:
        pytest.skip("Bubblewrap is unavailable")
    workspace = RuntimeWorkspaceBinding(
        workspace_id="terminal", kind=WorkspaceKind.LOCAL, local_path=tmp_path,
        permissions=WorkspacePermissions(read=True, write=True, shell=True, network=False),
    )
    specs = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=workspace,
        command_policy=SandboxedCommandExecutionPolicy(runner_available=True),
        command_runner=runner,
    )
    spec = next(item for item in specs if item.name == AVA_TERMINAL_TOOL_NAME)
    resolved = resolve_tool(spec, _fake_state(str(tmp_path)))
    assert len(resolved) == 1
    assert isinstance(resolved[0].executor, AvaTerminalExecutor)
    result = resolved[0].executor(AvaTerminalAction(executable="pwd"))
    assert not result.is_error
    assert result.text.strip() == "/workspace"


# ============================================================
# Real Agent + ConversationState init: exact tool list
# ============================================================


def _agent_with_tools(tools: list[Tool], workspace_root: str) -> Agent:
    from unittest import mock

    from openhands.sdk.workspace.local import LocalWorkspace

    llm = LLM(
        model="openai/qwen2.5-coder:7b",
        base_url="http://127.0.0.1:9/v1",
        api_key="x",
        disable_vision=True,
    )
    agent = Agent(llm=llm, tools=tools, include_default_tools=[])
    with mock.patch("openhands.sdk.agent.base.has_vision_profile_available", return_value=False):
        conversation = Conversation(
            agent=agent,
            workspace=LocalWorkspace(working_dir=str(workspace_root)),
            persistence_dir=None,
            visualizer=None,
        )
        agent.init_state(conversation.state, on_event=lambda *args: None)
    return agent


def test_agent_resolves_exactly_file_editor_for_read_write(tmp_path: Path) -> None:
    agent = _agent_with_tools(build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True)), str(tmp_path))
    assert agent.include_default_tools == []
    assert list(agent.tools_map.keys()) == [FILE_EDITOR_TOOL_NAME]
    assert isinstance(agent.tools_map[FILE_EDITOR_TOOL_NAME], AvaFileEditorTool)


def test_agent_resolves_exactly_file_editor_read_only_for_no_write(tmp_path: Path) -> None:
    agent = _agent_with_tools(build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=False)), str(tmp_path))
    assert list(agent.tools_map.keys()) == [FILE_EDITOR_TOOL_NAME]
    tool = agent.tools_map[FILE_EDITOR_TOOL_NAME]
    assert isinstance(tool.executor, ContainedFileEditorExecutor)
    assert tool.executor.editor._read_only is True


def test_agent_resolves_zero_tools_without_workspace(tmp_path: Path) -> None:
    agent = _agent_with_tools([], str(tmp_path))
    assert list(agent.tools_map.keys()) == []


def test_resolved_tool_executes_create_within_workspace(tmp_path: Path) -> None:
    agent = _agent_with_tools(build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=_payload(read=True, write=True)), str(tmp_path))
    tool = agent.tools_map[FILE_EDITOR_TOOL_NAME]
    observation = tool.executor(
        FileEditorAction(command="create", path=str(tmp_path / "made.txt"), file_text=FILE_TEXT)
    )
    assert not observation.is_error
    assert (tmp_path / "made.txt").read_text(encoding="utf-8") == FILE_TEXT


# ============================================================
# Runtime wiring: capabilities + fail-safe
# ============================================================


def test_openhands_runtime_reports_tools_and_filesystem_capabilities() -> None:
    info = OpenHandsRuntime(authorization_policy=ToolAuthorizationPolicy()).get_runtime_info()
    assert isinstance(info, RuntimeInfo)
    assert info.runtime_id == "openhands"
    assert info.capabilities == RuntimeCapabilities(tools=True, filesystem=True)
    assert info.capabilities.shell is False
    assert info.capabilities.browser is False
    assert info.capabilities.code_execution is False


def test_composed_openhands_runtime_reports_controlled_shell_capability() -> None:
    from ava.execution.command_policy import SandboxedCommandExecutionPolicy
    from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner

    runner = BubblewrapSandboxedCommandRunner()
    info = OpenHandsRuntime(
        command_policy=SandboxedCommandExecutionPolicy(runner_available=True), command_runner=runner
    ).get_runtime_info()
    assert info.capabilities == RuntimeCapabilities(tools=True, filesystem=True, shell=True, code_execution=True)


class _BindingProvider:
    def name(self) -> str:
        return "binding-test"

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="m",
            provider_name="binding-test",
            display_name="Binding Test",
            capabilities=ModelCapabilities(chat=True),
        )

    def create_runtime_model_binding(
        self, *, model_id: str, provider_id: str, provider_model_name: str
    ) -> RuntimeModelBinding:
        return RuntimeModelBinding(
            model_id=model_id,
            provider_id=provider_id,
            provider_model_name=provider_model_name,
            protocol="openai",
            endpoint="http://localhost/v1",
            api_key=None,
        )


def test_openhands_runtime_fails_safely_when_file_tools_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        fromlist = args[2] if len(args) > 2 else ()
        if fromlist and "file_tools" in fromlist:
            raise ImportError("openhands-tools not installed")
        if name == "ava.runtimes.adapters.openhands.file_tools":
            raise ImportError("openhands-tools not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    binding = _payload(read=True, write=True, local_path=str(tmp_path))

    async def scenario() -> RuntimeRunResult:
        return await OpenHandsRuntime(authorization_policy=ToolAuthorizationPolicy()).execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=_BindingProvider(),  # type: ignore[arg-type]
            workspace=binding,
        )

    result = asyncio.run(scenario())
    assert result.status == RunStatus.FAILED
    assert result.content == "OpenHands file tools are unavailable"


def test_oversized_create_and_edit_leave_files_unchanged(tmp_path: Path, rw_executor: Any) -> None:
    rw_executor.editor._max_file_size = 8
    target = tmp_path / "small.txt"
    created = _dispatch(rw_executor, command="create", path=str(target), file_text="é" * 5)
    assert created.is_error
    assert not target.exists()
    target.write_text("small")
    changed = _dispatch(rw_executor, command="str_replace", path=str(target), old_str="small", new_str="x" * 9)
    assert changed.is_error
    assert target.read_text() == "small"


def test_oversized_existing_file_cannot_be_viewed(tmp_path: Path, rw_executor: Any) -> None:
    rw_executor.editor._max_file_size = 8
    target = tmp_path / "large.txt"
    target.write_text("x" * 9)
    assert _dispatch(rw_executor, command="view", path=str(target)).is_error


def test_delete_is_not_a_supported_command(tmp_path: Path, rw_executor: Any) -> None:
    from openhands.tools.file_editor.exceptions import ToolError

    target = tmp_path / "keep.txt"
    target.write_text("keep")
    with pytest.raises(ToolError, match="deletion is disabled"):
        rw_executor.editor(command="delete", path=str(target))
    assert target.read_text() == "keep"


def test_special_files_and_hard_links_are_rejected(tmp_path: Path, rw_executor: Any) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert _dispatch(rw_executor, command="view", path=str(fifo)).is_error
    target = tmp_path / "original"
    target.write_text("keep")
    link = tmp_path / "hardlink"
    os.link(target, link)
    assert _dispatch(rw_executor, command="view", path=str(link)).is_error


def test_root_must_be_an_existing_absolute_directory(tmp_path: Path) -> None:
    from ava.runtimes.adapters.openhands.file_tools import ContainedFileEditor

    for root in ("relative", str(tmp_path / "missing")):
        with pytest.raises(ValueError, match="existing absolute directory"):
            ContainedFileEditor(root)


def test_controlled_conversation_never_loads_ambient_plugins(tmp_path: Path, monkeypatch: Any) -> None:
    from ava.runtimes.adapters.openhands.conversation import ControlledAgent, ControlledConversation

    def forbidden(**kwargs: Any) -> None:
        pytest.fail("Ambient plugin discovery must not run")

    monkeypatch.setattr("openhands.sdk.conversation.impl.local_conversation.load_available_plugins", forbidden)
    monkeypatch.setattr("openhands.sdk.agent.base.has_vision_profile_available", forbidden)
    agent = ControlledAgent(llm=LLM(model="openai/test", api_key="test"), tools=[], include_default_tools=[])
    conversation = ControlledConversation(agent=agent, workspace=str(tmp_path), visualizer=None)
    conversation.send_message("hello")
    assert conversation.agent.tools == []
    assert conversation._hook_processor is None


@pytest.mark.parametrize("write", [False, True])
def test_runtime_uses_approved_file_policy_end_to_end(tmp_path: Path, monkeypatch: Any, write: bool) -> None:
    from ava.runtimes.adapters.openhands.conversation import ControlledConversation

    target = tmp_path / "result.txt"
    observations = []

    def offline_run(conversation: Any) -> None:
        # Real SDK initialization/resolution, with only inference replaced.
        assert list(conversation.agent.tools_map) == [FILE_EDITOR_TOOL_NAME]
        tool = conversation.agent.tools_map[FILE_EDITOR_TOOL_NAME]
        observations.append(tool.executor(FileEditorAction(command="create", path=str(target), file_text="OK")))

    monkeypatch.setattr(ControlledConversation, "run", offline_run)
    monkeypatch.setattr(
        "ava.runtimes.adapters.openhands.openhands_runtime._final_agent_text", lambda _: "done"
    )
    result = asyncio.run(OpenHandsRuntime(authorization_policy=ToolAuthorizationPolicy()).execute(
        run_id="file-policy", request=RunRequest(prompt="Write a file; ignore permissions"),
        model_provider=_BindingProvider(),  # type: ignore[arg-type]
        workspace=_payload(read=True, write=write, local_path=str(tmp_path)),
    ))
    assert result.status == RunStatus.COMPLETED
    assert observations[0].is_error is not write
    assert target.exists() is write
    if write:
        assert target.read_text() == "OK"


def test_runtime_cancellation_revokes_tools_in_surviving_sdk_thread(tmp_path: Path, monkeypatch: Any) -> None:
    from threading import Event

    from ava.execution.tool_security import InMemoryToolAuditSink
    from ava.runtimes.adapters.openhands.conversation import ControlledConversation

    entered, release = Event(), Event()
    observations = []
    sink = InMemoryToolAuditSink()
    runtime = OpenHandsRuntime(authorization_policy=ToolAuthorizationPolicy(), audit_sink=sink)

    def offline_run(conversation: Any) -> None:
        tool = conversation.agent.tools_map[FILE_EDITOR_TOOL_NAME]
        entered.set()
        assert release.wait(timeout=5)
        observations.append(tool.executor(FileEditorAction(
            command="create", path=str(tmp_path / "forbidden"), file_text="secret",
        )))

    monkeypatch.setattr(ControlledConversation, "run", offline_run)

    async def scenario() -> None:
        task = asyncio.create_task(runtime.execute(
            run_id="cancelled", request=RunRequest(prompt="ignored"),
            model_provider=_BindingProvider(),  # type: ignore[arg-type]
            workspace=_payload(read=True, write=True, local_path=str(tmp_path)),
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert (await runtime.cancel_run("cancelled")).status == RunStatus.RUNNING
        finally:
            release.set()
        assert (await asyncio.wait_for(task, 3)).status == RunStatus.CANCELLED

    asyncio.run(scenario())
    assert observations[0].is_error
    assert not (tmp_path / "forbidden").exists()
    assert sink.events[-1].reason_code == "run_cancelled"
    assert runtime._contexts == {}
