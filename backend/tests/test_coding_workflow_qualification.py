"""Deterministic Step 35 coding-workflow result evaluation."""

from ava.runtimes.qualification import classify_workflow_stall, evaluate_coding_workflow


def test_coding_workflow_requires_real_edit_test_and_unchanged_tests() -> None:
    result = evaluate_coding_workflow(
        scenario_id="python_single_bug_repair", tests_passed=True, test_files_unchanged=True,
        expected_files_changed=True, native_tools_only=True, final_response="Tests pass.",
        file_editor_calls=3, terminal_calls=4, test_executions=2, failed_test_executions=1,
    )
    assert result.passed
    assert result.retries == 1


def test_coding_workflow_rejects_false_success_and_test_edits() -> None:
    result = evaluate_coding_workflow(
        scenario_id="python_single_bug_repair", tests_passed=False, test_files_unchanged=False,
        expected_files_changed=True, native_tools_only=True, final_response="The fix passed.",
        file_editor_calls=1, terminal_calls=1, test_executions=1, failed_test_executions=1,
    )
    assert not result.passed
    assert result.false_success_claimed
    assert result.failure_reason == "false_success_claimed"


def test_stall_classification_uses_partial_event_facts() -> None:
    assert classify_workflow_stall(
        tool_calls=2, file_editor_calls=2, terminal_calls=0, final_response_emitted=False, cancelled=True
    ) == "file_read_loop"
    assert classify_workflow_stall(
        tool_calls=0, file_editor_calls=0, terminal_calls=0, final_response_emitted=False, cancelled=True
    ) == "no_initial_action"
