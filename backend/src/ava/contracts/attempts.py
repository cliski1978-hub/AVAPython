"""Retry / regenerate eligibility policy for persisted runs.

Phase 5.31 vocabulary. These are pure predicates over the authoritative run
status, owned by the contract layer so the application service and the wire
contracts never restate them.

The two actions are distinct user intents, not two names for one operation:

    Retry      = a new run for the same source user message after an attempt
                 that did not produce a usable response
    Regenerate = a new run for the same source user message after an attempt
                 that succeeded

Both always create a *new* run with its own assistant response. Neither ever
reopens, resumes, or mutates the prior run: a terminal run is immutable
history.

``execution_interrupted`` (Phase 5.30's restart settlement) is an ordinary
``failed`` status, so it is retryable under the same rule as any other failure
and needs no special case. The code lives on the run's error payload, not on
its status, and this policy deliberately does not branch on it.
"""

from ava.contracts.responses import RunStatus

# ============================================================
# BEGIN: Attempt Policy
# ============================================================


#: Prior statuses a retry may supersede. A failure and a stopped run both
#: left the user without a usable response for that turn.
RETRYABLE_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.FAILED, RunStatus.CANCELLED}
)

#: Prior statuses a regenerate may supersede. Regeneration is the user's
#: request for a different answer to a turn that already produced one.
REGENERATABLE_RUN_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.COMPLETED})


def can_retry(status: RunStatus) -> bool:
    """Whether retrying from a run in this status is allowed.

    Deliberately narrow: a successful response is regenerated, not retried, so
    the two actions never appear as indistinguishable buttons over one status.
    """
    return status in RETRYABLE_RUN_STATUSES


def can_regenerate(status: RunStatus) -> bool:
    """Whether regenerating from a run in this status is allowed."""
    return status in REGENERATABLE_RUN_STATUSES


def can_be_superseded(status: RunStatus) -> bool:
    """Whether a new attempt may be created against a run in this status.

    This is the single backend guard, and it is status-based rather than
    action-based: the backend cannot tell a retry from a regenerate (that
    intent is application-local), but both require the prior attempt to have
    settled. An active run is never a target, so a stale client can never
    branch a still-executing turn.
    """
    return status.is_terminal


# ============================================================
# END: Attempt Policy
# ============================================================
