"""Focused tests for the normalized execution boundary; all authorities are test-only."""

from dataclasses import replace
from pathlib import Path

import pytest
from test_tool_policy import PolicyFixture

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.execution import ExecutionMode
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse
from ava.contracts.tool_features import UpdateToolFeaturesRequest
from ava.contracts.tools import (
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolRequest,
    ToolResult,
    ToolRisk,
    ToolStatus,
)
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore
from ava.services.tool_execution_service import (
    InvocationReservationState,
    ToolExecutionDisposition,
    ToolExecutionService,
)
from ava.tools.authority import ToolOperationType


class _Executor:
    def __init__(self, status: ToolStatus = ToolStatus.COMPLETED) -> None:
        self.calls = 0
        self.status = status

    async def execute(self, invocation):
        self.calls += 1
        return ToolResult(
            invocation_id=invocation.request.invocation_id,
            tool_id=invocation.request.tool_id,
            tool_version=invocation.request.tool_version,
            status=self.status,
            error=(
                ErrorResponse(error_code="executor_cancelled", category=ErrorCategory.UNAVAILABLE, message="Cancelled")
                if self.status == ToolStatus.CANCELLED
                else None
            ),
            output={"text": "read"} if self.status == ToolStatus.COMPLETED else None,
        )


class _Reservations:
    durable = True

    def __init__(self) -> None:
        self.states: dict[str, InvocationReservationState] = {}
        self.fail_terminal_finalization = False

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

        if self.fail_terminal_finalization and state in {
            InvocationReservationState.COMPLETED,
            InvocationReservationState.FAILED,
        }:
            raise RuntimeError("simulated finalization failure")
        record = self.records[invocation_id]
        updated = replace(
            record, state=state, revision=expected_revision + 1, **{k: v for k, v in metadata.items() if v is not None}
        )
        self.records[invocation_id] = updated
        self.states[invocation_id] = state
        return updated

    def list_incomplete(self, *, limit=100):
        return ()

    def list_for_run(self, run_id):
        return tuple(record for record in getattr(self, "records", {}).values() if record.run_id == run_id)


def _setup(tmp_path: Path, mode: ExecutionMode):
    fixture = PolicyFixture(tmp_path)
    fixture.authority.grant = replace(fixture.authority.grant, run_id="run-1")
    runs = RunStore()
    runs.create("run-1", execution_mode=mode)
    executor = _Executor()
    reservations = _Reservations()
    service = ToolExecutionService(
        runs=runs,
        registry=fixture.registry,
        features=fixture.features,
        policy=fixture.service(),
        authority=fixture.authority,
        executors={"test.read": executor, "test.write": executor},
        reservations=reservations,
    )
    request = ToolRequest(
        invocation_id="invocation-1",
        tool_id="test.read",
        tool_version="1",
        arguments={"path": "source.txt"},
        execution_context_ref="context-1",
        run_id="run-1",
    )
    return service, request, executor, reservations


@pytest.mark.asyncio
async def test_chat_mode_denies_tool_requests_even_with_test_authority(tmp_path: Path) -> None:
    service, request, executor, _ = _setup(tmp_path, ExecutionMode.CHAT)
    outcome = await service.execute(request)
    assert outcome.disposition == ToolExecutionDisposition.DENIED
    assert outcome.policy_reason == "chat_tool_execution_disabled"
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_unknown_tool_and_missing_authority_are_denied(tmp_path: Path) -> None:
    service, request, executor, _ = _setup(tmp_path, ExecutionMode.AGENT)
    unknown = request.model_copy(update={"tool_id": "test.unknown"})
    assert (await service.execute(unknown)).policy_reason == "unknown_tool"
    service._authority = None
    outcome = await service.execute(request)
    assert outcome.policy_reason == "execution_authority_unavailable"
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_plan_mode_rejects_mutating_effects(tmp_path: Path) -> None:
    service, request, executor, _ = _setup(tmp_path, ExecutionMode.PLAN)
    write_request = request.model_copy(
        update={"tool_id": "test.write", "arguments": {"path": "new.txt", "content": "x"}}
    )
    outcome = await service.execute(write_request)
    assert outcome.disposition == ToolExecutionDisposition.DENIED
    assert outcome.policy_reason == "plan_mode_read_only"
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_plan_mode_rejects_mixed_effect_metadata(tmp_path: Path) -> None:
    fixture = PolicyFixture(tmp_path)
    fixture.authority.grant = replace(fixture.authority.grant, run_id="run-1")
    fixture.registry.register(
        ToolDefinition(
            tool_id="test.mixed",
            name="Mixed operation",
            description="Declares both read and write capabilities",
            tool_version="1",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            output_schema={"type": "object"},
            required_capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        )
    )
    fixture.features.update(
        UpdateToolFeaturesRequest(
            framework_enabled=True,
            enabled_tool_ids=tuple([*fixture.operations, "test.mixed"]),
            expected_version=1,
        )
    )
    fixture.operations["test.mixed"] = ToolOperationType.READ
    policy = fixture.service()
    runs = RunStore()
    runs.create("run-1", execution_mode=ExecutionMode.PLAN)
    service = ToolExecutionService(
        runs=runs,
        registry=fixture.registry,
        features=fixture.features,
        policy=policy,
        authority=fixture.authority,
    )
    outcome = await service.execute(
        ToolRequest(
            invocation_id="mixed-invocation",
            tool_id="test.mixed",
            tool_version="1",
            arguments={"path": "source.txt"},
            execution_context_ref="context-1",
            run_id="run-1",
        )
    )
    assert outcome.policy_reason == "plan_mode_effects_not_read_only"


@pytest.mark.asyncio
async def test_preflight_allow_never_dispatches_without_durable_reservation(tmp_path: Path) -> None:
    service, request, executor, _ = _setup(tmp_path, ExecutionMode.PLAN)
    service._reservations = None
    outcome = await service.execute(request)
    assert outcome.disposition == ToolExecutionDisposition.DENIED
    assert outcome.preflight_decision == "allow"
    assert outcome.policy_reason == "durable_invocation_reservation_unavailable"
    assert not outcome.authorized_for_dispatch
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_plan_read_dispatch_requires_and_uses_atomic_reservation(tmp_path: Path) -> None:
    service, request, executor, reservations = _setup(tmp_path, ExecutionMode.PLAN)
    outcome = await service.execute(request)
    assert outcome.disposition == ToolExecutionDisposition.EXECUTED
    assert outcome.authorized_for_dispatch
    assert outcome.result is not None and outcome.result.status == ToolStatus.COMPLETED
    assert executor.calls == 1
    assert reservations.states[request.invocation_id] == InvocationReservationState.COMPLETED


@pytest.mark.asyncio
async def test_executor_confirmed_cancellation_is_not_persisted_as_failure(tmp_path: Path) -> None:
    service, request, _, reservations = _setup(tmp_path, ExecutionMode.PLAN)
    executor = _Executor(ToolStatus.CANCELLED)
    service._executors[request.tool_id] = executor

    outcome = await service.execute(request)

    assert outcome.disposition == ToolExecutionDisposition.CANCELLED
    assert outcome.result is not None and outcome.result.status == ToolStatus.CANCELLED
    assert reservations.states[request.invocation_id] == InvocationReservationState.CANCELLED
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_duplicate_invocation_cannot_dispatch_twice(tmp_path: Path) -> None:
    service, request, executor, _ = _setup(tmp_path, ExecutionMode.PLAN)
    assert (await service.execute(request)).disposition == ToolExecutionDisposition.EXECUTED
    duplicate = await service.execute(request)
    assert duplicate.disposition == ToolExecutionDisposition.DENIED
    assert duplicate.policy_reason == "duplicate_invocation"
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_failed_outcome_finalization_is_returned_as_indeterminate(tmp_path: Path) -> None:
    service, request, executor, reservations = _setup(tmp_path, ExecutionMode.PLAN)
    reservations.fail_terminal_finalization = True
    outcome = await service.execute(request)
    assert outcome.result is not None
    assert outcome.result.status == ToolStatus.INDETERMINATE
    assert reservations.states[request.invocation_id] == InvocationReservationState.INDETERMINATE
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_executor_failure_with_failed_state_write_returns_indeterminate(tmp_path: Path) -> None:
    service, request, executor, reservations = _setup(tmp_path, ExecutionMode.PLAN)

    async def fail_execution(invocation):
        del invocation
        executor.calls += 1
        raise RuntimeError("simulated executor failure")

    executor.execute = fail_execution
    reservations.fail_terminal_finalization = True
    outcome = await service.execute(request)
    assert outcome.result is not None
    assert outcome.result.status == ToolStatus.INDETERMINATE
    assert reservations.states[request.invocation_id] == InvocationReservationState.INDETERMINATE
    assert executor.calls == 1


def test_execution_mode_contract_defaults_to_chat() -> None:
    from ava.contracts.requests import RunRequest

    assert RunRequest(prompt="hello").execution_mode == ExecutionMode.CHAT


def test_run_mode_is_persisted_for_memory_and_relational_repositories(tmp_path: Path) -> None:
    from ava.infrastructure.persistence.composition import create_relational_repositories

    memory = RunStore()
    assert memory.create("memory-chat").execution_mode == ExecutionMode.CHAT
    assert memory.create("memory-plan", execution_mode=ExecutionMode.PLAN).execution_mode == ExecutionMode.PLAN

    repositories = create_relational_repositories(str(tmp_path / "runs.sqlite3"))
    try:
        default_run = repositories.run_repository.create("db-chat")
        plan_run = repositories.run_repository.create("db-plan", execution_mode=ExecutionMode.PLAN)
        assert default_run.execution_mode == ExecutionMode.CHAT
        assert plan_run.execution_mode == ExecutionMode.PLAN
        assert repositories.run_repository.get("db-plan").execution_mode == ExecutionMode.PLAN
    finally:
        repositories.dispose()


def test_run_service_captures_mode_once_on_new_run() -> None:
    runs = RunStore()
    service = RunService(object(), run_repository=runs, run_event_repository=RunEventStore())  # type: ignore[arg-type]
    prepared = service.prepare_run(RunRequest(prompt="planning", execution_mode=ExecutionMode.PLAN))
    assert not isinstance(prepared, RunResponse)
    run = runs.get(prepared.run_id)
    assert run is not None and run.execution_mode == ExecutionMode.PLAN
    response = service.get_run(prepared.run_id)
    assert response is not None and response.execution_mode == ExecutionMode.PLAN
    event = service.get_run_events(prepared.run_id)[0]
    assert event.payload["execution_mode"] == "plan"


def test_production_composition_has_no_dispatch_authority_or_adapters() -> None:
    from ava.api.app import create_app
    from ava.configuration.settings import Settings

    app = create_app(settings=Settings(persistence_provider="memory"))
    execution = app.state.tool_execution_service
    assert execution._authority is None
    assert execution._executors == {}
    assert execution._reservations is not None
    assert execution._reservations.durable is False
