from dataclasses import asdict

from ava.execution.tool_security import InMemoryToolAuditSink, ToolAuditEvent, ToolRunContext


def test_metadata_only_event_contract() -> None:
    sink = InMemoryToolAuditSink()
    context = ToolRunContext("run", "runtime", sink)
    context.record("file_editor", "file.read", "success", "allowed")
    event, = sink.events
    assert set(asdict(event)) == {
        "run_id", "runtime_id", "tool_id", "action", "outcome", "reason_code", "timestamp",
    }
    assert event.timestamp.tzinfo is not None
    assert event.run_id == "run"


def test_audit_failure_is_logged_and_does_not_change_authorization(caplog: object) -> None:
    class BrokenSink:
        def record(self, event: ToolAuditEvent) -> None:
            raise RuntimeError("AVA_FAKE_SECRET_DO_NOT_LEAK")

    context = ToolRunContext("run", "runtime", BrokenSink())
    context.record("ava_terminal", "tool.activate", "denied", "workspace_shell_denied")
    assert not context.revoked.is_set()
    assert "Security audit sink failed" in str(caplog.text)
    assert "AVA_FAKE_SECRET_DO_NOT_LEAK" not in str(caplog.text)
