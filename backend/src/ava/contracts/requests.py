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
    """

    prompt: str = Field(min_length=1)
    execution: RunExecutionOverride | None = None
    workspace_id: str | None = None
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
