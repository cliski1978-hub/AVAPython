"""Contract definitions for AVA errors.

Framework-neutral error DTOs. Vendor SDK objects must never appear here.
Public errors must not expose stack traces or sensitive implementation
information.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from ava.contracts.json_types import JsonValue
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Error Categories
# ============================================================


class ErrorCategory(StrEnum):
    """Normalized AVA error categories."""

    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER = "provider"
    AGENT = "agent"
    INTERNAL = "internal"


# ============================================================
# END: Error Categories
# ============================================================


# ============================================================
# BEGIN: Error Response
# ============================================================


class ErrorResponse(BaseModel):
    """Response contract for API errors.

    `error_code` is a stable machine-readable identifier maintained by AVA.
    `details` may carry additional structured JSON-safe context but must never
    contain stack traces, passwords, API keys, tokens, provider SDK objects,
    sensitive internal paths, or credential information.
    """

    error_code: str
    category: ErrorCategory
    message: str
    recoverable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)
    correlation_id: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Error Response
# ============================================================