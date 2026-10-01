import asyncio

import pytest

from ava.contracts.requests import RunRequest
from ava.execution.persisted_execution import (
    ConfiguredModelIneligibleError,
    ConfiguredReferenceMissingError,
    CredentialResolutionFailedError,
    ExecutionDefaultsNotConfiguredError,
    ProviderAdapterNotRegisteredError,
    RuntimeAdapterNotRegisteredError,
)
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore


class FailingAgent:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def start_run_streaming(self, **_: object):
        raise self.error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ExecutionDefaultsNotConfiguredError(), "configuration_missing"),
        (ProviderAdapterNotRegisteredError("connection", "missing"), "provider_connection_unavailable"),
        (ConfiguredModelIneligibleError("model"), "model_unavailable"),
        (RuntimeAdapterNotRegisteredError("runtime", "missing"), "runtime_unavailable"),
        (CredentialResolutionFailedError("connection"), "credential_unavailable"),
        (ConfiguredReferenceMissingError("provider connection", "missing"), "configuration_invalid"),
    ],
)
def test_configuration_failure_is_persisted_as_safe_run_failed_event(error, code):
    events = RunEventStore()
    service = RunService(FailingAgent(error), run_repository=RunStore(), run_event_repository=events)
    response = asyncio.run(service.start_run(RunRequest(prompt="test")))
    assert response.status == "failed"
    failed = [event for event in events.get_events(response.run_id) if event.event_type == "run_failed"]
    assert failed[-1].payload["error_code"] == code
    assert "SUPER_SECRET_SHOULD_NEVER_APPEAR" not in str(failed[-1].payload)
