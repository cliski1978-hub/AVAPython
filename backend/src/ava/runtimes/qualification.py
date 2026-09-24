"""Measured model qualification for runtime-native tool calling.

This is intentionally separate from provider compatibility and runtime
capabilities.  A runtime may implement a tool safely while a model is unable
to request it through the provider's structured tool-call protocol.
"""

from dataclasses import dataclass
from enum import StrEnum


class ToolCallQualificationFailure(StrEnum):
    NATIVE_TOOL_CALL_SUCCESS = "native_tool_call_success"
    TOOL_CALL_EMITTED_AS_TEXT = "tool_call_emitted_as_text"
    WRONG_TOOL_SELECTED = "wrong_tool_selected"
    MALFORMED_TOOL_ARGUMENTS = "malformed_tool_arguments"
    NO_TOOL_CALL = "no_tool_call"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_RESULT_NOT_CONSUMED = "tool_result_not_consumed"
    FINAL_RESPONSE_MISSING = "final_response_missing"
    RUNTIME_FAILURE = "runtime_failure"


@dataclass(frozen=True)
class ToolCallQualificationTrial:
    """Observable outcomes of one runtime-native tool-call attempt."""

    native_tool_name: str | None = None
    native_tool_call_observed: bool = False
    malformed_tool_arguments: bool = False
    tool_executed: bool = False
    sandbox_receipt_observed: bool = False
    tool_result_observed: bool = False
    final_response_observed: bool = False
    assistant_text: str | None = None
    runtime_failed: bool = False


@dataclass(frozen=True)
class ToolCallQualificationResult:
    """Aggregate result for a repeatable model/runtime/tool workload."""

    model_id: str
    expected_tool_name: str
    trials: int
    native_tool_calls: int
    textual_pseudo_tool_calls: int
    malformed_tool_calls: int
    successful_executions: int
    successful_tool_result_consumption: int
    final_responses: int
    passed: bool
    failure_reasons: tuple[ToolCallQualificationFailure, ...]


@dataclass(frozen=True)
class CodingWorkflowQualificationResult:
    """Measured outcome of a contained coding-agent scenario."""

    scenario_id: str
    passed: bool
    tests_passed: bool
    test_files_unchanged: bool
    expected_files_changed: bool
    native_tools_only: bool
    false_success_claimed: bool
    file_editor_calls: int
    terminal_calls: int
    test_executions: int
    failed_test_executions: int
    retries: int
    failure_reason: str | None


def classify_workflow_stall(
    *, tool_calls: int, file_editor_calls: int, terminal_calls: int,
    final_response_emitted: bool, cancelled: bool,
) -> str | None:
    """Classify a bounded run from observable events, never hidden reasoning."""
    if final_response_emitted:
        return None
    if not cancelled:
        return "completion_not_emitted"
    if tool_calls == 0:
        return "no_initial_action"
    if file_editor_calls > 0 and terminal_calls == 0:
        return "file_read_loop"
    if terminal_calls > 0:
        return "tool_result_not_consumed"
    return "unknown_stall"


def evaluate_coding_workflow(
    *,
    scenario_id: str,
    tests_passed: bool,
    test_files_unchanged: bool,
    expected_files_changed: bool,
    native_tools_only: bool,
    final_response: str | None,
    file_editor_calls: int,
    terminal_calls: int,
    test_executions: int,
    failed_test_executions: int,
) -> CodingWorkflowQualificationResult:
    """Evaluate observable workflow facts without interpreting model prose."""
    response = (final_response or "").lower()
    false_success = not tests_passed and any(word in response for word in ("pass", "fixed", "success"))
    passed = (
        tests_passed
        and test_files_unchanged
        and expected_files_changed
        and native_tools_only
        and not false_success
        and file_editor_calls > 0
        and test_executions > 0
    )
    if passed:
        reason = None
    elif false_success:
        reason = "false_success_claimed"
    elif not tests_passed:
        reason = "tests_not_passing"
    elif not test_files_unchanged:
        reason = "tests_modified"
    elif not expected_files_changed:
        reason = "expected_source_not_changed"
    elif not native_tools_only:
        reason = "non_native_tool_activity"
    elif file_editor_calls == 0:
        reason = "no_file_editor_edit"
    else:
        reason = "tests_not_executed"
    return CodingWorkflowQualificationResult(
        scenario_id=scenario_id,
        passed=passed,
        tests_passed=tests_passed,
        test_files_unchanged=test_files_unchanged,
        expected_files_changed=expected_files_changed,
        native_tools_only=native_tools_only,
        false_success_claimed=false_success,
        file_editor_calls=file_editor_calls,
        terminal_calls=terminal_calls,
        test_executions=test_executions,
        failed_test_executions=failed_test_executions,
        retries=max(0, failed_test_executions),
        failure_reason=reason,
    )


def classify_tool_call_trial(
    trial: ToolCallQualificationTrial, *, expected_tool_name: str
) -> ToolCallQualificationFailure:
    """Classify evidence without turning assistant text into an action.

    Only an SDK-native event can set ``native_tool_call_observed``. Text that
    resembles a tool call is evidence of incompatibility, never an executable
    request.
    """
    if trial.runtime_failed:
        return ToolCallQualificationFailure.RUNTIME_FAILURE
    if not trial.native_tool_call_observed:
        if trial.assistant_text and expected_tool_name in trial.assistant_text:
            return ToolCallQualificationFailure.TOOL_CALL_EMITTED_AS_TEXT
        return ToolCallQualificationFailure.NO_TOOL_CALL
    if trial.native_tool_name != expected_tool_name:
        return ToolCallQualificationFailure.WRONG_TOOL_SELECTED
    if trial.malformed_tool_arguments:
        return ToolCallQualificationFailure.MALFORMED_TOOL_ARGUMENTS
    if not trial.tool_executed or not trial.sandbox_receipt_observed:
        return ToolCallQualificationFailure.TOOL_EXECUTION_FAILED
    if not trial.tool_result_observed:
        return ToolCallQualificationFailure.TOOL_RESULT_NOT_CONSUMED
    if not trial.final_response_observed:
        return ToolCallQualificationFailure.FINAL_RESPONSE_MISSING
    return ToolCallQualificationFailure.NATIVE_TOOL_CALL_SUCCESS


def qualify_native_tool_calls(
    *, model_id: str, expected_tool_name: str, trials: tuple[ToolCallQualificationTrial, ...]
) -> ToolCallQualificationResult:
    """Aggregate trials; qualification requires every observed trial to pass."""
    reasons = tuple(classify_tool_call_trial(trial, expected_tool_name=expected_tool_name) for trial in trials)
    return ToolCallQualificationResult(
        model_id=model_id,
        expected_tool_name=expected_tool_name,
        trials=len(trials),
        native_tool_calls=sum(trial.native_tool_call_observed for trial in trials),
        textual_pseudo_tool_calls=sum(
            reason == ToolCallQualificationFailure.TOOL_CALL_EMITTED_AS_TEXT for reason in reasons
        ),
        malformed_tool_calls=sum(trial.malformed_tool_arguments for trial in trials),
        successful_executions=sum(
            trial.tool_executed and trial.sandbox_receipt_observed for trial in trials
        ),
        successful_tool_result_consumption=sum(
            trial.tool_result_observed and trial.final_response_observed for trial in trials
        ),
        final_responses=sum(trial.final_response_observed for trial in trials),
        passed=bool(trials)
        and all(
            reason == ToolCallQualificationFailure.NATIVE_TOOL_CALL_SUCCESS for reason in reasons
        ),
        failure_reasons=reasons,
    )
