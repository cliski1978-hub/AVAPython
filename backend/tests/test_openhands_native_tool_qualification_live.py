"""Opt-in live Step 34C qualification; excluded from ordinary CI."""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from ava.execution.sandbox import SandboxedCommandRequest
from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner
from ava.runtimes.adapters.openhands.qualification import run_native_tool_call_trial, run_openhands_workflow
from ava.runtimes.qualification import evaluate_coding_workflow, qualify_native_tool_calls
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions

pytestmark = pytest.mark.skipif(
    os.getenv("AVA_RUN_LOCAL_MODEL_QUALIFICATION") != "1",
    reason="set AVA_RUN_LOCAL_MODEL_QUALIFICATION=1 to run local-model qualification",
)


def test_local_model_native_ava_terminal_qualification(tmp_path: Path) -> None:
    runner = BubblewrapSandboxedCommandRunner()
    if not runner.available:
        pytest.skip("Bubblewrap is unavailable")
    model_id = os.getenv("AVA_QUALIFICATION_MODEL", "qwen2.5-coder:7b")
    endpoint = os.getenv("AVA_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    context_window = int(os.getenv("AVA_QUALIFICATION_CONTEXT", "8192"))
    workspace = RuntimeWorkspaceBinding(
        workspace_id="native-tool-qualification",
        kind=WorkspaceKind.LOCAL,
        local_path=tmp_path,
        permissions=WorkspacePermissions(read=True, write=False, shell=True, network=False),
    )
    trials = tuple(
        asyncio.run(run_native_tool_call_trial(
            model_id=model_id, endpoint=endpoint, workspace=workspace, runner=runner,
            context_window=context_window,
        ))
        for _ in range(3)
    )
    result = qualify_native_tool_calls(
        model_id=model_id, expected_tool_name="ava_terminal", trials=trials
    )
    print(result)
    # Baseline discovery may legitimately fail. A selected candidate can make
    # this a gate with AVA_QUALIFICATION_REQUIRE_PASS=1.
    if os.getenv("AVA_QUALIFICATION_REQUIRE_PASS") == "1":
        assert result.passed, result
    assert result.trials == 3


def _write_single_bug_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "label_normalizer.py"
    tests = root / "tests" / "test_label_normalizer.py"
    tests.parent.mkdir()
    source.write_text(
        "def normalize_labels(values):\n"
        "    return [str(value).strip().lower() for value in values if value]\n"
    )
    tests.write_text(
        "import unittest\n\n"
        "from label_normalizer import normalize_labels\n\n\n"
        "class NormalizeLabelsTests(unittest.TestCase):\n"
        "    def test_normalizes_values_without_discarding_zero(self):\n"
        "        self.assertEqual(normalize_labels([' Beta ', '', 0, 'ALPHA']), ['beta', '0', 'alpha'])\n"
    )
    return source, tests


async def _run_fixture_tests(runner: BubblewrapSandboxedCommandRunner, root: Path, command_id: str):
    return await runner.execute(SandboxedCommandRequest(
        command_id=command_id,
        executable="python",
        arguments=("-m", "unittest", "discover", "-s", "tests"),
        workspace_root=root,
        working_directory=Path("."),
        workspace_writable=True,
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout_seconds=30,
        network_allowed=False,
    ))


def test_local_model_single_bug_repair_workflow(tmp_path: Path) -> None:
    runner = BubblewrapSandboxedCommandRunner()
    if not runner.available:
        pytest.skip("Bubblewrap is unavailable")
    model_id = os.getenv("AVA_QUALIFICATION_MODEL", "qwen2.5-coder:7b")
    endpoint = os.getenv("AVA_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    context_window = int(os.getenv("AVA_QUALIFICATION_CONTEXT", "8192"))
    source, tests = _write_single_bug_fixture(tmp_path)
    initial_source = source.read_text()
    initial_test_hash = hashlib.sha256(tests.read_bytes()).hexdigest()
    baseline = asyncio.run(_run_fixture_tests(runner, tmp_path, "workflow-baseline"))
    assert baseline.exit_code != 0
    workspace = RuntimeWorkspaceBinding(
        workspace_id="coding-workflow",
        kind=WorkspaceKind.LOCAL,
        local_path=tmp_path,
        permissions=WorkspacePermissions(read=True, write=True, shell=True, network=False),
    )
    trace = asyncio.run(run_openhands_workflow(
        model_id=model_id,
        endpoint=endpoint,
        workspace=workspace,
        runner=runner,
        context_window=context_window,
        prompt=(
            "The tests in this project are failing. Inspect the project, determine the cause, "
            "fix the implementation, and run python -m unittest discover -s tests until it passes. "
            "Do not modify tests. When finished, summarize the bug, implementation change, and test result."
        ),
    ))
    final = asyncio.run(_run_fixture_tests(runner, tmp_path, "workflow-final"))
    result = evaluate_coding_workflow(
        scenario_id="python_single_bug_repair",
        tests_passed=final.exit_code == 0,
        test_files_unchanged=hashlib.sha256(tests.read_bytes()).hexdigest() == initial_test_hash,
        expected_files_changed=source.read_text() != initial_source,
        native_tools_only=set(trace.tool_names).issubset({"file_editor", "ava_terminal"}),
        final_response=trace.final_response,
        file_editor_calls=trace.tool_names.count("file_editor"),
        terminal_calls=trace.tool_names.count("ava_terminal"),
        test_executions=sum("unittest" in arguments for arguments in trace.terminal_arguments),
        failed_test_executions=trace.terminal_failures,
    )
    print(trace)
    print(result)
    assert result.passed, result
