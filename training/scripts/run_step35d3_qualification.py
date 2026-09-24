"""Run the frozen, opt-in Step 35D.3 Granite base-versus-adapter evaluation.

This runner never reads the SFT datasets, persists no model reasoning, and
creates a fresh disposable holdout fixture for each model/trial.  It records
only observable event facts and deterministic post-run workspace validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ava.execution.sandbox import SandboxedCommandRequest
from ava.infrastructure.sandbox.bubblewrap_runner import BubblewrapSandboxedCommandRunner
from ava.runtimes.adapters.openhands.qualification import run_openhands_workflow
from ava.workspaces.contracts import RuntimeWorkspaceBinding, WorkspaceKind, WorkspacePermissions


REPORT_PATH = Path(__file__).parents[1] / "deployment" / "reports" / "step35d3-base-vs-adapter.json"
CONTEXT_WINDOW = 8192
TEMPERATURE = 1
TOP_P = 0.95
TIMEOUT_SECONDS = 60
MAX_ITERATIONS = 5
HARD_TRIAL_TIMEOUT_SECONDS = 70
MODELS = (
    ("control", "ava-granite4.2-base-control:8b-q4km"),
    ("adapter", "ava-granite4.2-agent-sft-v1:8b-q4km"),
)
SCENARIOS = (
    ("A", 1, "Read label_normalizer.py using the available file tool and tell me what the normalize_labels function does.\nDo not modify any files."),
    ("B", 1, "Read label_normalizer.py and tests/test_label_normalizer.py.\nDo not modify anything.\nExplain why the failing zero-value case is likely failing."),
    ("C", 1, "In label_normalizer.py, change the implementation so integer 0 is preserved and converted to \"0\".\nDo not run tests.\nMake only the required source change and then report the file you modified."),
    ("D", 1, "Run the project's tests using the available terminal tool.\nDo not modify any files.\nReport the failing test."),
    ("E", 2, "The implementation incorrectly drops integer 0.\n\nFix label_normalizer.py so 0 is preserved as \"0\".\nThen run the tests.\nIf they pass, report what you changed and the test result.\nDo not modify the tests."),
    ("F", 2, "The tests in this project are failing.\n\nInspect the project, determine the cause, fix the implementation, and run the tests until they pass.\n\nDo not modify the tests unless the tests themselves are clearly invalid.\n\nWhen finished, summarize the bug, the change you made, and the final test result."),
)


def write_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "label_normalizer.py"
    tests = root / "tests" / "test_label_normalizer.py"
    tests.parent.mkdir(parents=True)
    source.write_text("def normalize_labels(values):\n    return [str(value).strip().lower() for value in values if value]\n")
    tests.write_text(
        "import unittest\n\nfrom label_normalizer import normalize_labels\n\n\n"
        "class NormalizeLabelsTests(unittest.TestCase):\n"
        "    def test_normalizes_values_without_discarding_zero(self):\n"
        "        self.assertEqual(normalize_labels([' Beta ', '', 0, 'ALPHA']), ['beta', '0', 'alpha'])\n"
    )
    return source, tests


async def run_tests(runner: BubblewrapSandboxedCommandRunner, root: Path, command_id: str):
    return await runner.execute(SandboxedCommandRequest(
        command_id=command_id, executable="python",
        arguments=("-m", "unittest", "discover", "-s", "tests"),
        workspace_root=root, working_directory=Path("."), workspace_writable=True,
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout_seconds=30, network_allowed=False,
    ))


def semantic_tree(root: Path) -> dict[str, str]:
    ignored = {"__pycache__", ".pytest_cache"}
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file() and not any(part in ignored for part in path.parts):
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def response_has_final(trace: Any) -> bool:
    return bool(trace.final_response and trace.run_completed)


def preserves_integer_zero(source: str) -> bool:
    namespace: dict[str, Any] = {}
    try:
        exec(source, namespace)
        return namespace["normalize_labels"]([" Beta ", "", 0, "ALPHA"]) == ["beta", "0", "alpha"]
    except Exception:
        return False


async def run_trial(
    *, runner: BubblewrapSandboxedCommandRunner, candidate: str, model_id: str,
    scenario_id: str, trial: int, prompt: str,
) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"ava-step35d3-{candidate}-{scenario_id.lower()}-"))
    try:
        source, tests = write_fixture(root)
        before_tree = semantic_tree(root)
        source_before = source.read_text()
        tests_before = tests.read_bytes()
        baseline = await run_tests(runner, root, f"{candidate}-{scenario_id}-{trial}-baseline")
        if baseline.exit_code == 0:
            raise RuntimeError("fixture baseline unexpectedly passed")
        workspace = RuntimeWorkspaceBinding(
            workspace_id=f"step35d3-{candidate}-{scenario_id}-{trial}", kind=WorkspaceKind.LOCAL,
            local_path=root, permissions=WorkspacePermissions(read=True, write=True, shell=True, network=False),
        )
        started = time.monotonic()
        trace = await run_openhands_workflow(
            model_id=model_id, endpoint=os.getenv("AVA_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"),
            workspace=workspace, runner=runner, prompt=prompt, context_window=CONTEXT_WINDOW,
            temperature=TEMPERATURE, timeout_seconds=TIMEOUT_SECONDS, max_iterations=MAX_ITERATIONS,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        final = await run_tests(runner, root, f"{candidate}-{scenario_id}-{trial}-final")
        after_tree = semantic_tree(root)
        source_after = source.read_text()
        tests_unchanged = tests.read_bytes() == tests_before
        source_correct = preserves_integer_zero(source_after)
        tool_names = trace.tool_names
        final_text = (trace.final_response or "").lower()
        diagnosis_correct = "zero" in final_text and ("drop" in final_text or "truth" in final_text or "if value" in final_text)
        false_success = final.exit_code != 0 and any(word in final_text for word in ("pass", "fixed", "success"))
        file_editor_calls = tool_names.count("file_editor")
        terminal_calls = tool_names.count("ava_terminal")
        tests_run_by_model = any("unittest" in arguments for arguments in trace.terminal_arguments)
        no_semantic_changes = before_tree == after_tree
        common = {
            "candidate": candidate, "model_id": model_id, "scenario": scenario_id, "trial": trial,
            "baseline_failed": baseline.exit_code != 0, "tests_passed": final.exit_code == 0,
            "tests_unchanged": tests_unchanged, "source_changed": source_after != source_before,
            "source_correct": source_correct, "no_unexpected_files": set(after_tree) <= set(before_tree),
            "native_tools_only": set(tool_names).issubset({"file_editor", "ava_terminal"}),
            "file_editor_calls": file_editor_calls, "terminal_calls": terminal_calls,
            "sandbox_requests": trace.sandbox_requests, "test_executions": int(tests_run_by_model),
            "failed_test_executions": trace.terminal_failures, "final_response_emitted": bool(trace.final_response),
            "run_completed": trace.run_completed, "false_success_claimed": false_success,
            "stall_reason": trace.stall_reason, "duration_ms": duration_ms,
            "event_trace": trace.event_trace,
            "first_action_ms": next((event[2] for event in trace.event_trace if event[0] == "ActionEvent"), None),
            "final_response_ms": next((event[2] for event in trace.event_trace if event[0] == "AgentMessageEvent"), None),
        }
        if scenario_id == "A":
            passed = file_editor_calls >= 1 and terminal_calls == 0 and no_semantic_changes and bool(final_text) and response_has_final(trace)
        elif scenario_id == "B":
            passed = file_editor_calls >= 2 and terminal_calls == 0 and no_semantic_changes and diagnosis_correct and response_has_final(trace)
        elif scenario_id == "C":
            passed = source_correct and tests_unchanged and set(after_tree) == set(before_tree) and response_has_final(trace)
        elif scenario_id == "D":
            passed = terminal_calls >= 1 and tests_run_by_model and final.exit_code != 0 and no_semantic_changes and diagnosis_correct and response_has_final(trace)
        else:
            passed = source_correct and final.exit_code == 0 and tests_unchanged and tests_run_by_model and response_has_final(trace) and not false_success
        common["result"] = "PASS" if passed else ("PARTIAL" if source_correct or file_editor_calls or terminal_calls else "FAIL")
        return common
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def main() -> None:
    if os.getenv("AVA_RUN_LOCAL_MODEL_QUALIFICATION") != "1":
        raise SystemExit("set AVA_RUN_LOCAL_MODEL_QUALIFICATION=1 to run this live evaluation")
    runner = BubblewrapSandboxedCommandRunner()
    if not runner.available:
        raise SystemExit("Bubblewrap is unavailable")
    results: list[dict[str, Any]] = []
    for scenario_id, trials, prompt in SCENARIOS:
        for trial in range(1, trials + 1):
            for candidate, model_id in MODELS:
                output = Path(tempfile.mkstemp(prefix="ava-step35d3-result-", suffix=".json")[1])
                command = [
                    sys.executable, str(Path(__file__).resolve()), "--single",
                    candidate, model_id, scenario_id, str(trial), str(output),
                ]
                started = time.monotonic()
                process = subprocess.Popen(command, start_new_session=True)
                try:
                    process.wait(timeout=HARD_TRIAL_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    results.append({
                        "candidate": candidate, "model_id": model_id, "scenario": scenario_id,
                        "trial": trial, "result": "PARTIAL", "baseline_failed": True,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "stall_reason": "evaluator_hard_timeout", "harness_timeout": True,
                    })
                else:
                    if process.returncode != 0 or not output.exists():
                        raise RuntimeError(f"single-trial evaluator failed: {candidate} {scenario_id} {trial}")
                    results.append(json.loads(output.read_text()))
                finally:
                    output.unlink(missing_ok=True)
                    subprocess.run(["ollama", "stop", model_id], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {
        "schema_version": 1,
        "step": "35D.3",
        "frozen_configuration": {
            "context_window": CONTEXT_WINDOW, "temperature": TEMPERATURE, "top_p": TOP_P,
            "timeout_seconds": TIMEOUT_SECONDS, "max_iterations": MAX_ITERATIONS,
            "seed": None, "seed_note": "The existing Ollama/OpenHands route has no explicit seeded evaluation path.",
            "fixture": "label_normalizer integer-zero holdout", "tool_surface": ["file_editor", "ava_terminal"],
        },
        "provenance": {
            "base_model": "ibm-granite/granite-4.2-8b", "base_revision": "7fce579a7fbbad4b1e7703b6850cefd517a4002b",
            "adapter": "granite-4.2-8b-ava-agent-sft-v1", "dataset": "ava-agent-sft-v1",
            "control_model": MODELS[0][1], "adapter_model": MODELS[1][1], "ollama_version": "0.33.3",
        },
        "results": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {REPORT_PATH}")
    for result in results:
        print(result["scenario"], result["trial"], result["candidate"], result["result"])


if __name__ == "__main__":
    if len(sys.argv) == 7 and sys.argv[1] == "--single":
        _, _, candidate_arg, model_arg, scenario_arg, trial_arg, output_arg = sys.argv
        prompt_arg = next(prompt for scenario, _, prompt in SCENARIOS if scenario == scenario_arg)
        single_runner = BubblewrapSandboxedCommandRunner()
        if not single_runner.available:
            raise SystemExit("Bubblewrap is unavailable")
        single_result = asyncio.run(run_trial(
            runner=single_runner, candidate=candidate_arg, model_id=model_arg,
            scenario_id=scenario_arg, trial=int(trial_arg), prompt=prompt_arg,
        ))
        Path(output_arg).write_text(json.dumps(single_result, indent=2) + "\n")
    else:
        asyncio.run(main())
