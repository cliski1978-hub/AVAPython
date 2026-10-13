"""AVA-owned tool values, not authorization, dispatch, or lifecycle services.

Context references and definition metadata never grant authority. Future
services must resolve trusted context, validate arguments against the selected
definition, and recheck current policy before any side effect.
"""

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ava.contracts.errors import ErrorResponse
from ava.contracts.json_types import JsonValue
from ava.contracts.version import CONTRACT_VERSION

ToolIdentifier = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=128)
]
ToolReference = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=256)]
ToolText = Annotated[str, StringConstraints(strict=True, min_length=1)]
OperationDigest = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolCapability(StrEnum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    COMMAND_EXECUTION = "command_execution"
    NETWORK_ACCESS = "network_access"


class ToolApprovalRequirement(StrEnum):
    """Definition's minimum requirement; policy may be stricter, never bypassed."""

    POLICY = "policy"
    REQUIRED = "required"


class ToolExecutionCategory(StrEnum):
    DETERMINISTIC = "deterministic"
    AGENTIC = "agentic"
    HYBRID = "hybrid"


class ToolStatus(StrEnum):
    """Facts about one invocation, independent of RunStatus or transitions."""

    REQUESTED = "requested"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    DENIED = "denied"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INTERRUPTED = "interrupted"
    INDETERMINATE = "indeterminate"


TERMINAL_TOOL_STATUSES = frozenset(
    {
        ToolStatus.COMPLETED,
        ToolStatus.FAILED,
        ToolStatus.DENIED,
        ToolStatus.CANCELLED,
        ToolStatus.EXPIRED,
        ToolStatus.REVOKED,
        ToolStatus.INTERRUPTED,
        ToolStatus.INDETERMINATE,
    }
)


def _require_json(value: object, depth: int = 0) -> None:
    """Reject coercible non-JSON inputs and non-finite numbers before Pydantic."""
    if depth > 32:
        raise ValueError("JSON nesting exceeds 32 levels")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, dict) and type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            _require_json(child, depth + 1)
        return
    if isinstance(value, list) and type(value) is list:
        for child in value:
            _require_json(child, depth + 1)
        return
    raise ValueError("value must contain only finite JSON values")


_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_SCHEMA_KEYS = {
    "type",
    "title",
    "description",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
}


def _require_schema(schema: object, *, root: bool = False) -> None:
    """Validate AVA's explicitly bounded JSON Schema subset, not instances.

    No references, executable validators, remote dialects, or unknown keywords.
    Every node declares one type; object/array/string/numeric constraints may
    only occur on the corresponding type. Full schema evolution is deferred.
    """
    if not isinstance(schema, dict) or not schema or set(schema) - _SCHEMA_KEYS:
        raise ValueError("unsupported or invalid tool schema")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _SCHEMA_TYPES or (root and kind != "object"):
        raise ValueError("schema requires a supported type; root must be object")
    for key in ("title", "description"):
        if key in schema and not isinstance(schema[key], str):
            raise ValueError(f"schema {key} must be a string")
    properties = schema.get("properties", {})
    if any(key in schema for key in ("properties", "required", "additionalProperties")):
        if kind != "object" or not isinstance(properties, dict):
            raise ValueError("object constraints require object type and properties")
        for name, child in properties.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("schema property names must not be blank")
            _require_schema(child)
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
            raise ValueError("required must be a list of property names")
        if len(required) != len(set(required)) or any(name not in properties for name in required):
            raise ValueError("required names must be unique declared properties")
        additional = schema.get("additionalProperties", True)
        if type(additional) is not bool:
            _require_schema(additional)
    if "items" in schema:
        if kind != "array":
            raise ValueError("items requires array type")
        _require_schema(schema["items"])
    if kind == "array" and "items" not in schema:
        raise ValueError("array schema requires items")
    for lower, upper, types in (
        ("minLength", "maxLength", {"string"}),
        ("minItems", "maxItems", {"array"}),
        ("minimum", "maximum", {"number", "integer"}),
    ):
        for key in (lower, upper):
            if key not in schema:
                continue
            value = schema[key]
            if kind not in types or type(value) not in (int, float):
                raise ValueError(f"invalid schema constraint {key}")
            if lower != "minimum" and (type(value) is not int or value < 0):
                raise ValueError(f"{key} must be a nonnegative integer")
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ValueError("schema lower bound exceeds upper bound")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            raise ValueError("schema enum must be a nonempty JSON list")


class _ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("contract_version")
    @classmethod
    def supported_contract_version(cls, value: str) -> str:
        if value != CONTRACT_VERSION:
            raise ValueError("unsupported tool contract version")
        return value


class ToolDefinition(_ToolContract):
    """Declaration only: no enablement, permission, or runtime binding."""

    tool_id: ToolIdentifier
    name: ToolText
    description: ToolText
    tool_version: ToolReference
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    required_capabilities: tuple[ToolCapability, ...] = ()
    risk: ToolRisk
    approval_requirement: ToolApprovalRequirement = ToolApprovalRequirement.POLICY
    execution_category: ToolExecutionCategory

    @field_validator("name", "description")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tool text must not be blank")
        return value

    @field_validator("input_schema", "output_schema", mode="before")
    @classmethod
    def valid_schema(cls, value: object) -> object:
        _require_json(value)
        _require_schema(value, root=True)
        return value

    @field_validator("required_capabilities")
    @classmethod
    def unique_capabilities(cls, value: tuple[ToolCapability, ...]) -> tuple[ToolCapability, ...]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class ToolExecutionContext(_ToolContract):
    """Reference-only context descriptor, never a trusted grant by itself.

    Future server resolution must verify provenance, scope, revocation and
    current policy. Missing references cannot default to unrestricted access.
    Workspace identity is distinct from its authorization reference. Runtime
    capabilities and model selection do not belong in this authority value.
    """

    context_id: ToolReference
    workspace_id: ToolReference | None = None
    workspace_authorization_ref: ToolReference | None = None
    tool_policy_ref: ToolReference | None = None
    caller_authority_ref: ToolReference | None = None

    @model_validator(mode="after")
    def workspace_reference_has_identity(self) -> Self:
        if self.workspace_authorization_ref is not None and self.workspace_id is None:
            raise ValueError("Workspace authorization reference requires Workspace identity")
        return self


class ToolRequest(_ToolContract):
    """Untrusted invocation intent. Arguments are JSON-ready, not authorized."""

    invocation_id: ToolReference
    tool_id: ToolIdentifier
    tool_version: ToolReference
    arguments: dict[str, JsonValue]
    execution_context_ref: ToolReference
    run_id: ToolReference | None = None
    correlation_id: ToolReference | None = None

    @field_validator("arguments", mode="before")
    @classmethod
    def json_arguments(cls, value: object) -> object:
        _require_json(value)
        if type(value) is not dict:
            raise ValueError("tool arguments must be a JSON object")
        return value


class ToolOperationBinding(_ToolContract):
    """Future approval binding to exact validated operation and authority state.

    SHA-256 operation_digest must cover canonical validated arguments,
    resource identities/expected revisions and all authority references below.
    Digest generation, trusted resolution and matching are future services;
    accepting this value is not an approval decision.
    """

    invocation_id: ToolReference
    tool_id: ToolIdentifier
    tool_version: ToolReference
    execution_context_ref: ToolReference
    operation_digest: OperationDigest
    authority_revision_ref: ToolReference


class ToolExecutionMetadata(_ToolContract):
    """Descriptive historical identities; these do not confer authority."""

    execution_context_ref: ToolReference
    workspace_id: ToolReference | None = None
    runtime_id: ToolReference | None = None
    model_id: ToolReference | None = None
    duration_seconds: float | None = Field(default=None, ge=0, strict=True)


class ToolResult(_ToolContract):
    invocation_id: ToolReference
    tool_id: ToolIdentifier
    tool_version: ToolReference
    status: ToolStatus
    output: dict[str, JsonValue] | None = None
    error: ErrorResponse | None = None
    artifact_refs: tuple[ToolReference, ...] = ()
    execution_metadata: ToolExecutionMetadata | None = None

    @field_validator("error", mode="before")
    @classmethod
    def json_error_details(cls, value: object) -> object:
        if isinstance(value, ErrorResponse):
            _require_json(value.details)
        elif isinstance(value, dict):
            _require_json(value.get("details", {}))
        return value

    @field_validator("output", mode="before")
    @classmethod
    def json_output(cls, value: object) -> object:
        _require_json(value)
        if value is not None and type(value) is not dict:
            raise ValueError("tool output must be a JSON object")
        return value

    @model_validator(mode="after")
    def terminal_outcome(self) -> Self:
        if self.error is not None and (not self.error.error_code.strip() or not self.error.message.strip()):
            raise ValueError("normalized error code and message must not be blank")
        if self.status not in TERMINAL_TOOL_STATUSES:
            raise ValueError("tool result must have a terminal status")
        if self.status == ToolStatus.COMPLETED:
            if self.error is not None or self.output is None:
                raise ValueError("completed result requires output and no error")
        elif self.status != ToolStatus.CANCELLED and self.error is None:
            raise ValueError("unsuccessful result requires normalized error")
        return self


class ToolLifecycleEvent(_ToolContract):
    """Standalone typed tool fact; no RunEvent emission/transition behavior.

    Sequence allocation, uniqueness, persistence, approval checks and run
    pause/resume are deferred. IDs/status here describe facts, never grants.
    """

    event_id: ToolReference
    invocation_id: ToolReference
    tool_id: ToolIdentifier
    tool_version: ToolReference
    execution_context_ref: ToolReference
    status: ToolStatus
    timestamp: datetime
    run_id: ToolReference | None = None
    correlation_id: ToolReference | None = None
    operation_binding: ToolOperationBinding | None = None
    approval_ref: ToolReference | None = None

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("tool event timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def matching_binding(self) -> Self:
        binding = self.operation_binding
        if binding is not None and (
            binding.invocation_id != self.invocation_id
            or binding.tool_id != self.tool_id
            or binding.tool_version != self.tool_version
            or binding.execution_context_ref != self.execution_context_ref
        ):
            raise ValueError("operation binding must match event invocation, tool and context")
        if self.status in {
            ToolStatus.APPROVAL_REQUIRED,
            ToolStatus.APPROVED,
            ToolStatus.EXPIRED,
        } and (binding is None or self.approval_ref is None):
            raise ValueError("approval lifecycle fact requires binding and approval reference")
        if self.approval_ref is not None and binding is None:
            raise ValueError("approval reference requires operation binding")
        return self
