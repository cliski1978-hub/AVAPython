"""Runtime bridge tests prove discovery and invocation use the normalized service."""

from dataclasses import replace
from pathlib import Path

import pytest
from test_tool_policy import PolicyFixture

from ava.contracts.execution import ExecutionMode
from ava.contracts.requests import RunRequest
from ava.contracts.tools import ToolResult, ToolStatus
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore
from ava.services.runtime_tool_bridge import ToolExecutionRuntimeBridge
from ava.services.tool_execution_service import InvocationReservationState, ToolExecutionService


class _Executor:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def execute(self, invocation):
        self.calls += 1
        if self.fail:
            raise RuntimeError("internal executor details")
        return ToolResult(
            invocation_id=invocation.request.invocation_id,
            tool_id=invocation.request.tool_id,
            tool_version=invocation.request.tool_version,
            status=ToolStatus.COMPLETED,
            output={"text": "safe result"},
        )


class _Reservations:
    durable = True

    def __init__(self) -> None:
        self.states = {}

    def reserve(self, reservation):
        if reservation.invocation_id in self.states:
            from ava.repositories.invocation_reservation_repository import InvocationReservationConflict

            raise InvocationReservationConflict("duplicate")
        self.records = getattr(self, "records", {})
        self.records[reservation.invocation_id] = reservation
        self.states[reservation.invocation_id] = reservation.state
        return reservation

    def get(self, invocation_id):
        return getattr(self, "records", {}).get(invocation_id)

    def transition(self, invocation_id, *, expected_revision, state, **metadata):
        from dataclasses import replace

        updated = replace(self.records[invocation_id], state=state, revision=expected_revision + 1,
                          **{k: v for k, v in metadata.items() if v is not None})
        self.records[invocation_id] = updated
        self.states[invocation_id] = state
        return updated

    def list_incomplete(self):
        return ()

    def list_for_run(self, run_id):
        return tuple(r for r in getattr(self, "records", {}).values() if r.run_id == run_id)


class _ContextRefs:
    def resolve(self, *, run_id, context, workspace):
        return "context-1"


def _setup(
    tmp_path: Path,
    mode: ExecutionMode,
    *,
    authority_enabled: bool = True,
    executor_failure: bool = False,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = PolicyFixture(tmp_path)
    fixture.authority.grant = replace(fixture.authority.grant, run_id="run-1")
    runs = RunStore()
    runs.create(
        "run-1",
        execution_mode=mode,
        owner_principal_ref="caller-1",
        owner_tenant_ref="tenant-1",
        owner_auth_context_ref="a" * 64,
        execution_workspace_id="workspace-1",
    )
    executor = _Executor(fail=executor_failure)
    reservations = _Reservations()
    events = RunEventStore()
    service = ToolExecutionService(
        runs=runs,
        registry=fixture.registry,
        features=fixture.features,
        policy=fixture.service(),
        authority=fixture.authority if authority_enabled else None,
        executors={"test.read": executor, "test.write": executor},
        reservations=reservations,
        run_events=events,
    )
    bridge = ToolExecutionRuntimeBridge(
        execution_service=service,
        context_refs=_ContextRefs(),
        events=events,
    )
    return bridge, service, executor, events, reservations


def test_discovery_uses_persisted_mode_and_fails_closed_without_authority(tmp_path: Path) -> None:
    plan, _, _, _, _ = _setup(tmp_path / "plan", ExecutionMode.PLAN)
    assert [item.tool_id for item in plan.discover_tools(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        context=None, workspace=None,
    )] == ["test.read"]

    chat, _, _, _, _ = _setup(tmp_path / "chat", ExecutionMode.CHAT)
    assert chat.discover_tools(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        context=None, workspace=None,
    ) == []

    unavailable, _, _, _, _ = _setup(tmp_path / "missing", ExecutionMode.PLAN, authority_enabled=False)
    assert unavailable.discover_tools(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
    ) == []


def test_agent_discovery_obeys_trusted_operation_and_workspace_scope(tmp_path: Path) -> None:
    bridge, service, _, _, _ = _setup(tmp_path, ExecutionMode.AGENT)
    assert [item.tool_id for item in bridge.discover_tools(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
    )] == ["test.read", "test.write"]

    authority = service._authority
    assert authority is not None
    authority.grant = replace(
        authority.grant,
        allowed_tool_ids=frozenset({"test.read", "test.write"}),
        workspace=replace(
            authority.grant.workspace,
            permissions=replace(authority.grant.workspace.permissions, write=False),
        ),
    )
    assert [item.tool_id for item in bridge.discover_tools(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
    )] == ["test.read"]


@pytest.mark.asyncio
async def test_bridge_binds_run_and_generated_invocation_then_uses_execution_service(tmp_path: Path) -> None:
    bridge, _, executor, events, reservations = _setup(tmp_path, ExecutionMode.PLAN)
    outcome = await bridge.execute_tool(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
        tool_id="test.read", tool_version="1", call_id="model-call", arguments_json='{"path":"source.txt"}',
    )
    assert outcome.disposition.value == "executed"
    assert outcome.result is not None and outcome.result.output == {"text": "safe result"}
    assert executor.calls == 1
    assert reservations.states[outcome.invocation_id] == InvocationReservationState.COMPLETED
    assert outcome.invocation_id != "model-call"
    assert [event.event_type.value for event in events.get_events("run-1")] == [
        "tool_requested",
        "tool_started",
        "tool_outcome",
    ]
    assert all(event.payload["execution_mode"] == "plan" for event in events.get_events("run-1"))
    assert "source.txt" not in str([event.payload for event in events.get_events("run-1")])
    assert "safe result" not in str([event.payload for event in events.get_events("run-1")])


@pytest.mark.asyncio
async def test_executor_failure_is_a_dispatched_outcome_not_a_rejection(tmp_path: Path) -> None:
    bridge, _, executor, events, _ = _setup(
        tmp_path, ExecutionMode.PLAN, executor_failure=True,
    )
    outcome = await bridge.execute_tool(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
        tool_id="test.read", tool_version="1", call_id="failed-call", arguments_json='{"path":"source.txt"}',
    )

    assert outcome.disposition.value == "failed"
    assert outcome.result is not None and outcome.result.status == ToolStatus.FAILED
    assert executor.calls == 1
    run_events = events.get_events("run-1")
    assert [event.event_type.value for event in run_events] == [
        "tool_requested",
        "tool_started",
        "tool_outcome",
    ]
    assert run_events[-1].payload["status"] == "failed"
    assert run_events[-1].payload["reason_code"] == "tool_execution_failed"


@pytest.mark.asyncio
async def test_invalid_arguments_and_unknown_tool_are_recorded_without_dispatch(tmp_path: Path) -> None:
    bridge, _, executor, events, _ = _setup(tmp_path, ExecutionMode.PLAN)
    malformed = await bridge.execute_tool(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
        tool_id="test.read", tool_version="1", call_id="model-call", arguments_json='{"path":NaN}',
    )
    unknown = await bridge.execute_tool(
        run_id="run-1", request=RunRequest(prompt="read"), context=None, workspace=None,
        tool_id="test.unknown", tool_version="unknown", call_id="model-call-2", arguments_json='{}',
    )
    assert malformed.disposition.value == "denied"
    assert unknown.disposition.value == "denied"
    assert executor.calls == 0
    assert [event.event_type.value for event in events.get_events("run-1")].count("tool_rejected") == 2


@pytest.mark.asyncio
async def test_repeated_provider_call_id_maps_to_same_invocation_and_cannot_dispatch_twice(tmp_path: Path) -> None:
    bridge, _, executor, _, _ = _setup(tmp_path, ExecutionMode.PLAN)
    kwargs = {
        "run_id": "run-1",
        "request": RunRequest(prompt="read"),
        "context": None,
        "workspace": None,
        "tool_id": "test.read",
        "tool_version": "1",
        "call_id": "stable-provider-call-id",
        "arguments_json": '{"path":"source.txt"}',
    }
    first = await bridge.execute_tool(**kwargs)
    repeated = await bridge.execute_tool(**kwargs)
    assert first.invocation_id == repeated.invocation_id
    assert first.disposition.value == "executed"
    assert repeated.disposition.value == "denied"
    assert repeated.reason_code == "duplicate_invocation"
    assert executor.calls == 1
