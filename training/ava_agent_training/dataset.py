"""Deterministic contract for synthetic AVA agent SFT trajectories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATASET_VERSION = "ava-agent-sft-v0"
TOOLS = {"file_editor", "ava_terminal"}
FILE_COMMANDS = {"view", "create", "str_replace", "insert", "undo_edit"}


class DatasetValidationError(ValueError):
    """A trajectory that cannot safely teach AVA's native tool protocol."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DatasetValidationError(message)


def validate_tool_call(call: dict[str, Any]) -> None:
    name = call.get("name")
    arguments = call.get("arguments")
    _require(name in TOOLS, "unknown or disabled tool")
    _require(isinstance(arguments, dict), "tool arguments must be structured object")
    if name == "ava_terminal":
        executable = arguments.get("executable")
        values = arguments.get("arguments", [])
        _require(isinstance(executable, str) and executable and "/" not in executable and " " not in executable,
                 "ava_terminal executable must be a bare program name")
        _require(isinstance(values, list) and all(isinstance(value, str) for value in values),
                 "ava_terminal arguments must be a string list")
        _require(not any(token in executable for token in ("bash", "sh")), "shell tools are not training targets")
    else:
        _require(arguments.get("command") in FILE_COMMANDS, "invalid file_editor command")
        _require(isinstance(arguments.get("path"), str), "file_editor path is required")


def validate_example(example: dict[str, Any]) -> None:
    metadata = example.get("metadata")
    messages = example.get("messages")
    _require(isinstance(metadata, dict), "metadata is required")
    _require(metadata.get("dataset_version") in {"ava-agent-sft-v0", "ava-agent-sft-v1"}, "wrong dataset version")
    _require(metadata.get("split") in {"train", "validation"}, "invalid split")
    _require(isinstance(messages, list) and len(messages) >= 3, "role-structured messages are required")
    _require(messages[0].get("role") == "system" and messages[1].get("role") == "user",
             "trajectory must begin system then user")
    pending: set[str] = set()
    test_verified = False
    for message in messages:
        role = message.get("role")
        _require(role in {"system", "user", "assistant", "tool"}, "unknown role")
        if role == "assistant":
            _require("pseudo_tool_call" not in message, "textual pseudo-tool calls are forbidden")
            calls = message.get("tool_calls", [])
            _require(isinstance(calls, list), "tool_calls must be a list")
            for call in calls:
                validate_tool_call(call)
                call_id = call.get("id")
                _require(isinstance(call_id, str) and call_id, "tool call id is required")
                pending.add(call_id)
        if role == "tool":
            call_id = message.get("tool_call_id")
            _require(call_id in pending, "tool result without matching call")
            pending.remove(call_id)
            if message.get("name") == "ava_terminal" and message.get("verified_tests_passed") is True:
                test_verified = True
    _require(not pending, "tool call missing result")
    final = messages[-1]
    _require(final.get("role") == "assistant" and not final.get("tool_calls"), "final assistant response required")
    content = str(final.get("content", "")).lower()
    if "tests pass" in content or "all tests pass" in content:
        _require(test_verified, "success claim without verified passing test result")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    examples = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for example in examples:
        validate_example(example)
    return examples


def validate_splits(train: list[dict[str, Any]], validation: list[dict[str, Any]]) -> None:
    train_ids = {item["metadata"]["scenario_id"] for item in train}
    validation_ids = {item["metadata"]["scenario_id"] for item in validation}
    _require(train_ids.isdisjoint(validation_ids), "train and validation scenario IDs overlap")
    forbidden = {"label_normalizer", "integer-zero", "test_label_normalizer"}
    corpus = json.dumps(train + validation).lower()
    _require(not any(token in corpus for token in forbidden), "Step 35 holdout entered the dataset")


def granite_messages(example: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt the contract to Transformers chat-template message fields."""
    output: list[dict[str, Any]] = []
    for message in example["messages"]:
        item = {key: value for key, value in message.items() if key not in {"tool_call_id", "verified_tests_passed"}}
        output.append(item)
    return output
