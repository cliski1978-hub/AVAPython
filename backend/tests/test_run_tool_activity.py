"""Run Inspector tool activity is a bounded, safe projection of durable facts."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.api.routes.runs import router as runs_router
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import ExecutionMode
from ava.repositories.invocation_reservation_repository import (
    InMemoryInvocationReservationRepository,
    InvocationReservation,
    InvocationReservationState,
)
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore


def _service(reservations=None):
    runs = RunStore()
    runs.create("run-1", execution_mode=ExecutionMode.AGENT)
    events = RunEventStore()
    return RunService(
        MockAgentAdapter(),
        run_repository=runs,
        run_event_repository=events,
        invocation_reservations=reservations,
    ), events


def _event(events: RunEventStore, event_type: EventType, invocation_id: str, status: str, **payload: object) -> None:
    events.append(
        RunEvent(
            event_id=f"event-{invocation_id}-{event_type.value}-{len(events.get_events('run-1'))}",
            run_id="run-1",
            event_type=event_type,
            timestamp=datetime(2026, 10, 14, 12, 0, len(events.get_events("run-1")), tzinfo=UTC),
            payload={
                "invocation_id": invocation_id,
                "tool_id": "workspace.read_file",
                "tool_version": "1",
                "execution_mode": "agent",
                "status": status,
                **payload,
            },
        )
    )


def _reservation(invocation_id: str, *, state=InvocationReservationState.INDETERMINATE):
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    return InvocationReservation(
        invocation_id=invocation_id,
        run_id="run-1",
        tool_id="workspace.read_file",
        tool_version="2",
        operation_fingerprint="a" * 64,
        workspace_id="workspace-1",
        execution_context_ref="context-private",
        authority_revision_ref="authority-private",
        configuration_revision_ref="tool-features:2",
        execution_mode="plan",
        state=state,
        revision=2,
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now if state in {
            InvocationReservationState.COMPLETED,
            InvocationReservationState.FAILED,
            InvocationReservationState.CANCELLED,
            InvocationReservationState.INDETERMINATE,
        } else None,
        result_status="indeterminate" if state == InvocationReservationState.INDETERMINATE else None,
        error_code=(
            "interrupted_execution_outcome_unknown"
            if state == InvocationReservationState.INDETERMINATE
            else None
        ),
        reconciliation_status="reconciled" if state == InvocationReservationState.INDETERMINATE else "not_required",
    )


def test_durable_reservation_overrides_a_conflicting_completed_event_without_leaking_binding() -> None:
    reservations = InMemoryInvocationReservationRepository()
    reservations.reserve(_reservation("inv-1"))
    service, events = _service(reservations)
    _event(events, EventType.TOOL_REQUESTED, "inv-1", "requested")
    _event(events, EventType.TOOL_STARTED, "inv-1", "started")
    _event(events, EventType.TOOL_OUTCOME, "inv-1", "completed")

    inspection = service.get_run_inspection("run-1")
    assert inspection is not None
    activity = inspection.tool_activity.items[0]
    assert activity.status == "indeterminate"
    assert activity.execution_mode == "plan"
    assert activity.recovery_status == "reconciled"
    assert activity.reason_code == "interrupted_execution_outcome_unknown"
    serialized = inspection.tool_activity.model_dump_json()
    for private_value in ("operation_fingerprint", "workspace_id", "context-private", "authority-private"):
        assert private_value not in serialized


def test_requested_rejected_failed_and_awaiting_approval_remain_distinct() -> None:
    service, events = _service()
    _event(events, EventType.TOOL_REQUESTED, "inv-request", "requested")
    _event(events, EventType.TOOL_REQUESTED, "inv-reject", "requested")
    _event(events, EventType.TOOL_REJECTED, "inv-reject", "denied", reason_code="tool_disabled")
    _event(events, EventType.TOOL_REQUESTED, "inv-fail", "requested")
    _event(events, EventType.TOOL_STARTED, "inv-fail", "started")
    _event(events, EventType.TOOL_OUTCOME, "inv-fail", "failed", reason_code="tool_execution_failed")
    _event(events, EventType.TOOL_REQUESTED, "inv-approval", "requested")
    _event(events, EventType.TOOL_OUTCOME, "inv-approval", "awaiting_approval")

    inspection = service.get_run_inspection("run-1")
    assert inspection is not None
    items = {item.invocation_id: item for item in inspection.tool_activity.items}
    assert items["inv-request"].status == "requested"
    assert items["inv-reject"].status == "rejected"
    assert items["inv-fail"].status == "failed"
    assert items["inv-approval"].status == "awaiting_approval"
    assert items["inv-approval"].approval_required is True
    assert items["inv-approval"].completed_at is None


def test_activity_history_is_bounded_and_ordered_to_latest_records() -> None:
    reservations = InMemoryInvocationReservationRepository()
    for index in range(102):
        reservations.reserve(_reservation(f"inv-{index:03d}", state=InvocationReservationState.RESERVED))
    service, _ = _service(reservations)

    inspection = service.get_run_inspection("run-1")
    assert inspection is not None
    assert len(inspection.tool_activity.items) == 100
    assert inspection.tool_activity.has_more is True
    assert inspection.tool_activity.items[0].invocation_id == "inv-002"
    assert inspection.tool_activity.items[-1].invocation_id == "inv-101"


def test_inconsistent_event_identity_is_omitted_and_repository_failure_is_unavailable() -> None:
    service, events = _service()
    _event(events, EventType.TOOL_REQUESTED, "inv-conflict", "requested")
    events.append(
        RunEvent(
            event_id="event-conflict",
            run_id="run-1",
            event_type=EventType.TOOL_STARTED,
            payload={"invocation_id": "inv-conflict", "tool_id": "different.tool", "status": "started"},
        )
    )
    inspection = service.get_run_inspection("run-1")
    assert inspection is not None and inspection.tool_activity.items == []

    class FailingHistory:
        def list_for_run(self, run_id: str, *, limit: int = 100):
            raise RuntimeError("private persistence detail")

    failing_service, _ = _service(FailingHistory())
    unavailable = failing_service.get_run_inspection("run-1")
    assert unavailable is not None and unavailable.tool_activity.available is False
    assert unavailable.tool_activity.items == []


def test_existing_run_inspection_api_returns_activity_and_keeps_unknown_run_boundary() -> None:
    reservations = InMemoryInvocationReservationRepository()
    reservations.reserve(_reservation("inv-api"))
    service, _ = _service(reservations)
    app = FastAPI()
    app.state.run_service = service
    app.include_router(runs_router)

    with TestClient(app) as client:
        response = client.get("/runs/run-1/inspection")
        unknown = client.get("/runs/unknown/inspection")

    assert response.status_code == 200
    body = response.json()
    assert body["tool_activity"]["items"][0]["status"] == "indeterminate"
    assert "operation_fingerprint" not in body["tool_activity"]["items"][0]
    assert unknown.status_code == 404
