"""Contract definitions for AVA requests.

Framework-neutral request DTOs. Vendor SDK objects must never appear here.
"""

from pydantic import BaseModel, Field, field_validator

from ava.contracts.execution import RunExecutionOverride
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Run Request
# ============================================================


class RunRequest(BaseModel):
    """Request contract for starting an AVA run.

    This contract is intentionally minimal for Sprint 1. Future sprints will
    add message, conversation, document-reference, and attachment fields.

    AVA owns and generates run identifiers. Callers must not supply them.
    For request correlation, a future ``correlation_id`` field may be added
    without overloading the run identifier.

    ``retry_of_run_id`` names the prior attempt a retry or regenerate branches
    from. It is a request-time intent only and is never persisted: the durable
    lineage is the shared ``source_user_message_id`` the new run inherits from
    the named run, so no parent-run column is added. When supplied, the prompt
    and source user message are resolved from the named run's durable records
    rather than trusted from the request, and the named run must already be
    terminal.
    """

    prompt: str = Field(min_length=1)
    conversation_id: str | None = None
    source_user_message_id: str | None = None
    execution: RunExecutionOverride | None = None
    workspace_id: str | None = None
    retry_of_run_id: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, value: str) -> str:
        """Reject prompts that are empty or contain only whitespace.

        Validation lives in the contract so routes and services never
        duplicate prompt rules.
        """
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


# ============================================================
# END: Run Request
# ============================================================
