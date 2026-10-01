"""Cold-start reconciliation for executions lost with their AVA process."""

from dataclasses import dataclass

from ava.repositories.run_repository import RunRepository
from ava.services.run_lifecycle_service import (
    InvalidRunTransitionError,
    RunLifecycleService,
)

#: The durable body of a restart-interrupted ``run_failed`` fact.
#:
#: The key is ``error_code`` because that is the canonical classification key
#: for a run failure: ``RunService`` writes it for every other failure, the
#: conversation projection reads it back to hydrate ``error_code`` after a
#: reload, and the frontend event processor reads it to choose the user-facing
#: wording. A restart interruption is a failure like any other, so it uses the
#: same key; anything else would persist a classification the UI can never see.
RESTART_INTERRUPTION_PAYLOAD = {
    "error_code": "execution_interrupted",
    "message": "The backend restarted before this run completed.",
}


@dataclass(frozen=True)
class RunRecoverySummary:
    active_found: int
    settled_failed: int


class RunRecoveryService:
    """Settle process-local active executions on cold application startup.

    Current AVA runtimes keep their execution tasks in process memory. A cold
    start therefore has no live owner for any persisted active run. This
    coordinator never contacts providers or runtimes and always delegates the
    actual transition/event write to the lifecycle authority.
    """

    def __init__(self, *, run_repository: RunRepository, lifecycle: RunLifecycleService) -> None:
        self._runs = run_repository
        self._lifecycle = lifecycle

    def recover_stranded_runs(self) -> RunRecoverySummary:
        active = list(self._runs.list_active())
        settled = 0
        for record in active:
            try:
                self._lifecycle.fail(record.run_id, payload=RESTART_INTERRUPTION_PAYLOAD)
                settled += 1
            except InvalidRunTransitionError:
                # A concurrent terminal writer won. It is already truthful;
                # never append a duplicate failure fact.
                continue
        return RunRecoverySummary(active_found=len(active), settled_failed=settled)
