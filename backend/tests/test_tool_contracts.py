"""Phase 6.2 value validation; no dispatcher, runtime or developer data."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.tools import (
    TERMINAL_TOOL_STATUSES,
    ToolApprovalRequirement,
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolExecutionContext,
    ToolExecutionMetadata,
    ToolLifecycleEvent,
    ToolOperationBinding,
    ToolRequest,
    ToolResult,
    ToolRisk,
    ToolStatus,
)


def definition_data() -> dict[str, object]:
    return {
        "tool_id": "file.read",
        "name": "Read file",
        "description": "Read one authorized resource.",
        "tool_version": "1.0.0",
        "risk": "low",
        "execution_category": "deterministic",
        "required_capabilities": ["file_read"],
        "input_schema": {
            "type": "object",
            "properties": {"resource_id": {"type": "string", "minLength": 1}},
            "required": ["resource_id"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    }


def request_data() -> dict[str, object]:
    return {
        "invocation_id": "inv-1",
        "tool_id": "file.read",
        "tool_version": "1.0.0",
        "arguments": {"resource_id": "resource-1"},
        "execution_context_ref": "ctx-1",
    }


def binding() -> ToolOperationBinding:
    return ToolOperationBinding(
        invocation_id="inv-1",
        tool_id="file.read",
        tool_version="1.0.0",
        execution_context_ref="ctx-1",
        operation_digest="a" * 64,
        authority_revision_ref="authority-rev-1",
    )


def event_data(status: ToolStatus) -> dict[str, object]:
    data: dict[str, object] = {
        "event_id": "event-1",
        "invocation_id": "inv-1",
        "tool_id": "file.read",
        "tool_version": "1.0.0",
        "execution_context_ref": "ctx-1",
        "status": status,
        "timestamp": datetime(2026, 10, 12, tzinfo=UTC),
    }
    if status in {ToolStatus.APPROVAL_REQUIRED, ToolStatus.APPROVED, ToolStatus.EXPIRED, ToolStatus.REVOKED}:
        data.update(operation_binding=binding(), approval_ref="approval-1")
    return data


def failure() -> ErrorResponse:
    return ErrorResponse(error_code="tool_unavailable", category=ErrorCategory.UNAVAILABLE, message="Tool unavailable")


def test_definition_preserves_schemas_and_describes_requirements_without_grants() -> None:
    value = ToolDefinition.model_validate(definition_data())
    assert value.risk is ToolRisk.LOW
    assert value.execution_category is ToolExecutionCategory.DETERMINISTIC
    assert value.required_capabilities == (ToolCapability.FILE_READ,)
    assert value.approval_requirement is ToolApprovalRequirement.POLICY
    assert value.input_schema == definition_data()["input_schema"]
    assert not {"enabled", "permissions", "authorized", "workspace_root"} & ToolDefinition.model_fields.keys()
    with pytest.raises(ValidationError):
        value.tool_id = "other.read"


@pytest.mark.parametrize("tool_id", ["", " ", "File.Read", "../read", "/read", "file..read", "file read", 1])
def test_invalid_tool_identity(tool_id: object) -> None:
    with pytest.raises(ValidationError):
        ToolDefinition.model_validate({**definition_data(), "tool_id": tool_id})


@pytest.mark.parametrize(
    "schema",
    [
        {},
        [],
        {"type": "unknown"},
        {"type": "string"},
        {"type": "object", "$ref": "https://vendor/schema"},
        {"type": "object", "properties": []},
        {"type": "object", "required": ["undeclared"]},
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x", "x"]},
        {"type": "object", "properties": {"x": {"type": "array"}}},
        {"type": "object", "properties": {"x": {"type": "boolean", "minLength": 1}}},
        {"type": "object", "properties": {"x": {"type": "string", "minLength": True}}},
        {"type": "object", "properties": {"x": {"type": "string", "minLength": 5, "maxLength": 2}}},
        {"type": "object", "properties": {"x": {"type": "number", "minimum": float("nan")}}},
        {"type": "object", "properties": {"x": {"type": "string", "enum": []}}},
        {"type": "object", "additionalProperties": 1},
    ],
)
@pytest.mark.parametrize("field", ["input_schema", "output_schema"])
def test_invalid_or_unsupported_schema(field: str, schema: object) -> None:
    with pytest.raises(ValidationError):
        ToolDefinition.model_validate({**definition_data(), field: schema})


def test_nested_schema_and_closed_approval_metadata() -> None:
    value = ToolDefinition.model_validate(
        {
            **definition_data(),
            "approval_requirement": "required",
            "input_schema": {
                "type": "object",
                "properties": {
                    "args": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "options": {"type": "object", "additionalProperties": {"type": "boolean"}},
                },
            },
        }
    )
    assert value.approval_requirement is ToolApprovalRequirement.REQUIRED
    for patch in (
        {"approval_requirement": "never"},
        {"required_capabilities": ["file_read", "file_read"]},
        {"execution_category": "openhands"},
        {"risk": "safe"},
        {"name": " \t"},
    ):
        with pytest.raises(ValidationError):
            ToolDefinition.model_validate({**definition_data(), **patch})


def test_request_is_validation_ready_json_and_supports_non_chat_invocation() -> None:
    arguments = {"resource_id": "resource-1", "options": [True, None, 4, 1.5, {"text": "日本語"}]}
    value = ToolRequest.model_validate({**request_data(), "arguments": arguments})
    assert value.arguments == arguments
    assert value.run_id is None
    # No instance-schema validation claim: a future service selects a definition.
    assert ToolRequest.model_validate({**request_data(), "arguments": {}}).arguments == {}


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        "text",
        None,
        {1: "x"},
        {"x": b"bytes"},
        {"x": object()},
        {"x": (1, 2)},
        {"x": float("inf")},
        {"x": float("nan")},
    ],
)
def test_request_rejects_non_json_argument_structure(arguments: object) -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate({**request_data(), "arguments": arguments})


@pytest.mark.parametrize(
    "field",
    [
        "permissions",
        "allow_shell",
        "workspace_root",
        "approval",
        "authorized",
        "runtime_id",
        "model_id",
        "credential",
        "enabled",
    ],
)
def test_request_cannot_submit_top_level_authority_or_selection(field: str) -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate({**request_data(), field: True})


def test_context_keeps_identity_separate_from_authorization_and_defaults_to_no_grants() -> None:
    value = ToolExecutionContext(context_id="ctx-1", workspace_id="workspace-1")
    assert value.workspace_authorization_ref is None
    assert value.tool_policy_ref is None
    assert value.caller_authority_ref is None
    for field in ("permissions", "local_path", "api_key", "approval_authority", "runtime_capabilities"):
        with pytest.raises(ValidationError):
            ToolExecutionContext.model_validate({"context_id": "ctx-1", field: "grant"})
    for reference in ("", " ", "/home/user", "../root", 12):
        with pytest.raises(ValidationError):
            ToolRequest.model_validate({**request_data(), "execution_context_ref": reference})


def test_result_success_failure_artifacts_and_descriptive_metadata() -> None:
    success = ToolResult(
        invocation_id="inv-1",
        tool_id="file.read",
        tool_version="1.0.0",
        status=ToolStatus.COMPLETED,
        output={"text": "Hello"},
        artifact_refs=("artifact-1",),
        execution_metadata=ToolExecutionMetadata(execution_context_ref="ctx-1", runtime_id="native"),
    )
    assert success.error is None
    assert success.output == {"text": "Hello"}
    failed = ToolResult(
        invocation_id="inv-1",
        tool_id="file.read",
        tool_version="1.0.0",
        status=ToolStatus.FAILED,
        error=failure(),
    )
    assert failed.error == failure()
    assert failed.output is None


@pytest.mark.parametrize("status", list(ToolStatus))
def test_result_accepts_only_consistent_terminal_outcomes(status: ToolStatus) -> None:
    data: dict[str, object] = {
        "invocation_id": "inv-1",
        "tool_id": "file.read",
        "tool_version": "1",
        "status": status,
    }
    if status == ToolStatus.COMPLETED:
        data["output"] = {}
    elif status != ToolStatus.CANCELLED:
        data["error"] = failure()
    if status in TERMINAL_TOOL_STATUSES:
        assert ToolResult.model_validate(data).status == status
    else:
        with pytest.raises(ValidationError, match="terminal status"):
            ToolResult.model_validate(data)


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "completed"},
        {"status": "completed", "output": {}, "error": failure()},
        {"status": "failed"},
        {"status": "completed", "output": {"sdk": object()}},
        {"status": "completed", "output": {"number": float("inf")}},
    ],
)
def test_inconsistent_or_vendor_result_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"invocation_id": "inv-1", "tool_id": "file.read", "tool_version": "1", **patch})


@pytest.mark.parametrize("status", list(ToolStatus))
def test_lifecycle_vocabulary_roundtrips_without_run_state_changes(status: ToolStatus) -> None:
    event = ToolLifecycleEvent.model_validate(event_data(status))
    assert ToolLifecycleEvent.model_validate_json(event.model_dump_json()) == event


def test_approval_fact_binds_exact_operation_without_deciding_or_authorizing() -> None:
    approved = event_data(ToolStatus.APPROVED)
    for patch in (
        {"operation_binding": None},
        {"approval_ref": None},
        {"operation_binding": binding().model_copy(update={"invocation_id": "inv-2"})},
    ):
        with pytest.raises(ValidationError):
            ToolLifecycleEvent.model_validate({**approved, **patch})
    for digest in ("", "sha256:abc", "A" * 64, "a" * 63):
        with pytest.raises(ValidationError):
            ToolOperationBinding.model_validate({**binding().model_dump(), "operation_digest": digest})
    assert "approved" not in ToolOperationBinding.model_fields


def test_lifecycle_rejects_invalid_status_and_naive_time() -> None:
    for patch in ({"status": "waiting_for_approval"}, {"timestamp": datetime(2026, 10, 12)}):
        with pytest.raises(ValidationError):
            ToolLifecycleEvent.model_validate({**event_data(ToolStatus.REQUESTED), **patch})


@pytest.mark.parametrize(
    "value",
    [
        ToolDefinition.model_validate(definition_data()),
        ToolRequest.model_validate(request_data()),
        ToolExecutionContext(context_id="ctx-1"),
        binding(),
        ToolExecutionMetadata(execution_context_ref="ctx-1", duration_seconds=0.5),
        ToolResult(invocation_id="inv-1", tool_id="file.read", tool_version="1", status=ToolStatus.CANCELLED),
    ],
)
def test_all_contracts_json_roundtrip_and_publish_pydantic_schema(value: BaseModel) -> None:
    assert type(value).model_validate_json(value.model_dump_json()) == value
    assert type(value).model_json_schema()["type"] == "object"
    with pytest.raises(ValidationError):
        type(value).model_validate({**value.model_dump(), "contract_version": "v2"})


def test_nested_json_limits_and_metadata_numbers() -> None:
    nested: object = None
    for _ in range(34):
        nested = [nested]
    with pytest.raises(ValidationError, match="nesting"):
        ToolRequest.model_validate({**request_data(), "arguments": {"x": nested}})
    for duration in (-1.0, float("inf"), float("nan"), "1.0", True):
        with pytest.raises(ValidationError):
            ToolExecutionMetadata.model_validate({"execution_context_ref": "ctx-1", "duration_seconds": duration})


def test_context_consistency_and_revocation_without_prior_approval() -> None:
    with pytest.raises(ValidationError):
        ToolExecutionContext(context_id="ctx-1", workspace_authorization_ref="grant-1")
    event = event_data(ToolStatus.REVOKED)
    event.pop("approval_ref")
    event.pop("operation_binding")
    assert ToolLifecycleEvent.model_validate(event).status is ToolStatus.REVOKED


@pytest.mark.parametrize(
    "error",
    [
        {"error_code": "bad", "category": "internal", "message": "Unavailable", "details": {"x": float("inf")}},
        failure().model_copy(update={"details": {"x": float("nan")}}),
        failure().model_copy(update={"message": " "}),
    ],
)
def test_result_error_details_are_finite_json_and_messages_nonblank(error: object) -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate(
            {
                "invocation_id": "inv-1",
                "tool_id": "file.read",
                "tool_version": "1",
                "status": "failed",
                "error": error,
            }
        )
