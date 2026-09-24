"""Deterministic Step 34C qualification policy tests."""

from ava.runtimes.qualification import (
    ToolCallQualificationFailure,
    ToolCallQualificationTrial,
    classify_tool_call_trial,
    qualify_native_tool_calls,
)


def test_textual_json_is_a_failure_and_never_an_execution() -> None:
    trial = ToolCallQualificationTrial(
        assistant_text='{"name":"ava_terminal","arguments":{"executable":"pwd"}}'
    )
    assert classify_tool_call_trial(trial, expected_tool_name="ava_terminal") == (
        ToolCallQualificationFailure.TOOL_CALL_EMITTED_AS_TEXT
    )
    result = qualify_native_tool_calls(model_id="candidate", expected_tool_name="ava_terminal", trials=(trial,))
    assert not result.passed
    assert result.successful_executions == 0


def test_native_tool_loop_requires_execution_result_and_final_response() -> None:
    complete = ToolCallQualificationTrial(
        native_tool_name="ava_terminal", native_tool_call_observed=True, tool_executed=True,
        sandbox_receipt_observed=True, tool_result_observed=True, final_response_observed=True,
    )
    result = qualify_native_tool_calls(
        model_id="candidate", expected_tool_name="ava_terminal", trials=(complete, complete, complete)
    )
    assert result.passed
    assert result.native_tool_calls == result.successful_executions == 3
    assert result.successful_tool_result_consumption == 3


def test_native_failures_are_classified_without_repair() -> None:
    malformed = ToolCallQualificationTrial(
        native_tool_name="ava_terminal", native_tool_call_observed=True, malformed_tool_arguments=True
    )
    wrong = ToolCallQualificationTrial(native_tool_name="file_editor", native_tool_call_observed=True)
    assert classify_tool_call_trial(malformed, expected_tool_name="ava_terminal") == (
        ToolCallQualificationFailure.MALFORMED_TOOL_ARGUMENTS
    )
    assert classify_tool_call_trial(wrong, expected_tool_name="ava_terminal") == (
        ToolCallQualificationFailure.WRONG_TOOL_SELECTED
    )
