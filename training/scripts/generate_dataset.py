"""Create reproducible synthetic AVA trajectories without qualification holdout data."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "ava-agent-sft-v0"


def call(call_id, name, arguments):
    return {"role": "assistant", "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}]}


def tool(call_id, name, content, passed=None):
    item = {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
    if passed is not None:
        item["verified_tests_passed"] = passed
    return item


def example(scenario_id, split, messages, capabilities, recovery=False):
    return {"metadata": {"dataset_version": DATASET_VERSION, "scenario_id": scenario_id, "split": split,
                         "capabilities": capabilities, "number_of_tool_calls": sum(len(m.get("tool_calls", [])) for m in messages),
                         "has_failure_recovery": recovery, "tests_verified": any(m.get("verified_tests_passed") for m in messages),
                         "source": "synthetic-standard-library"}, "messages": messages}


def repair(scenario_id, split, module, bug, recovery=False):
    msgs = [
        {"role": "system", "content": "You are AVA. Use only native file_editor and ava_terminal tools."},
        {"role": "user", "content": "Tests fail in this synthetic project. Diagnose and repair it without changing tests."},
        call("read-source", "file_editor", {"command": "view", "path": module + ".py"}),
        tool("read-source", "file_editor", bug),
        call("read-tests", "file_editor", {"command": "view", "path": "tests/test_" + module + ".py"}),
        tool("read-tests", "file_editor", "A standard-library unittest specifies the expected behavior."),
        call("edit-source", "file_editor", {"command": "str_replace", "path": module + ".py", "old_str": "BUG", "new_str": "FIXED"}),
        tool("edit-source", "file_editor", "Edit applied."),
    ]
    if recovery:
        msgs += [call("first-test", "ava_terminal", {"executable": "python", "arguments": ["-m", "unittest", "discover", "-s", "tests"]}),
                 tool("first-test", "ava_terminal", "FAIL: a boundary case remains", False),
                 call("second-edit", "file_editor", {"command": "str_replace", "path": module + ".py", "old_str": "FIXED", "new_str": "FIXED_WITH_BOUNDARY"}),
                 tool("second-edit", "file_editor", "Boundary edit applied.")]
    msgs += [call("test", "ava_terminal", {"executable": "python", "arguments": ["-m", "unittest", "discover", "-s", "tests"]}),
             tool("test", "ava_terminal", "OK", True),
             {"role": "assistant", "content": "Fixed the implementation and verified that all tests pass."}]
    return example(scenario_id, split, msgs, ["read", "edit", "test", "stop"], recovery)


def terminal_recovery(scenario_id, split):
    msgs = [{"role": "system", "content": "You are AVA. Use native structured tools."}, {"role": "user", "content": "List the workspace, correcting any tool error."},
            call("blocked", "ava_terminal", {"executable": "pwd", "arguments": []}), tool("blocked", "ava_terminal", "Command execution is not permitted by AVA policy.", False),
            call("retry", "ava_terminal", {"executable": "ls", "arguments": ["-la"]}), tool("retry", "ava_terminal", "workspace files", False),
            {"role": "assistant", "content": "The structured command completed; I will stop."}]
    return example(scenario_id, split, msgs, ["terminal-arguments", "stop"])


def main():
    (ROOT / "datasets").mkdir(parents=True, exist_ok=True)
    fixtures = [("slug-format", "slug_format", "Spaces are preserved"), ("range-boundary", "range_limit", "Upper boundary is excluded"),
                ("case-fold", "case_fold", "Mixed case is not normalized"), ("empty-value", "empty_value", "Empty input raises"),
                ("small-parser", "small_parser", "Delimiter parsing is incorrect")]
    train = [repair(f"{sid}-{index}", "train", module, bug, recovery=index % 2 == 0)
             for index in range(5) for sid, module, bug in fixtures]
    train += [terminal_recovery(f"structured-list-{index}", "train") for index in range(3)]
    validation = [repair(f"boolean-render-{index}", "validation", "boolean_render", "Boolean output is incorrect", recovery=index % 2 == 0)
                  for index in range(5)]
    for values, name in ((train, "train.jsonl"), (validation, "validation.jsonl")):
        (ROOT / "datasets" / name).write_text("".join(json.dumps(value, sort_keys=True) + "\n" for value in values))


if __name__ == "__main__":
    main()
