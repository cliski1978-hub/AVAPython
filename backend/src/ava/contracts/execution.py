"""Generic execution identity metadata for AVA runs."""

from enum import StrEnum

from pydantic import BaseModel, Field

from ava.contracts.models import ModelHostingMode
from ava.contracts.version import CONTRACT_VERSION


class RunExecutionSelection(BaseModel):
    """Stable identities selected by application composition for a run.

    ``hosting_mode`` is non-secret, descriptive deployment placement metadata:
    it answers "where did inference run?" for telemetry without exposing an
    endpoint, credential, or filesystem path.
    """

    runtime_id: str | None = None
    model_provider_id: str | None = None
    model_id: str | None = None
    hosting_mode: ModelHostingMode | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ExecutionSelectionMode(StrEnum):
    AUTO = "auto"


class RunExecutionOverride(BaseModel):
    """Optional per-run execution identity selection.

    ``model_id`` selects a stable AVA model identity (provider-neutral). It is
    preferred over ``model_provider_id``, which selects a provider only and
    binds its configured default model for backward compatibility. Clients never
    supply a provider-native model name or credentials.
    """

    mode: ExecutionSelectionMode | None = None
    runtime_id: str | None = None
    model_id: str | None = None
    model_provider_id: str | None = None
