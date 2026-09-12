"""Contract tests.

Verify that AVA contracts are framework-neutral, JSON-compatible, and carry
the current contract version.
"""

import json

import pytest
from pydantic import ValidationError

from ava.contracts.capabilities import CapabilityName
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.models import (
    ModelInfo,
    ModelMessage,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import (
    CapabilitiesResponse,
    HealthResponse,
    HealthStatus,
    RunResponse,
    RunStatus,
)
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Contract Serialization Tests
# ============================================================


def test_health_response_serializes_to_json() -> None:
    """HealthResponse should serialize with the contract version."""
    response = HealthResponse(status=HealthStatus.HEALTHY, application="AVA")
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "status": "healthy",
        "application": "AVA",
        "contract_version": CONTRACT_VERSION,
    }


def test_health_status_values() -> None:
    """HealthStatus enum should expose expected values."""
    assert HealthStatus.HEALTHY == "healthy"
    assert HealthStatus.UNHEALTHY == "unhealthy"


# ============================================================
# END: Contract Serialization Tests
# ============================================================


# ============================================================
# BEGIN: Versioning Tests
# ============================================================


def test_contract_version_is_v1() -> None:
    """The current contract version should be v1."""
    assert CONTRACT_VERSION == "v1"


# ============================================================
# END: Versioning Tests
# ============================================================


# ============================================================
# BEGIN: Run Contract Tests
# ============================================================


def test_run_request_serializes_to_json_with_version() -> None:
    """RunRequest should serialize with the contract version."""
    request = RunRequest(prompt="Summarize the document")
    payload = request.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["prompt"] == "Summarize the document"
    assert payload["contract_version"] == CONTRACT_VERSION


def test_run_request_does_not_accept_run_id() -> None:
    """AVA owns run identifiers; callers must not supply them."""
    request = RunRequest(prompt="Summarize the document")
    assert "run_id" not in request.model_dump()


def test_run_request_rejects_empty_prompt() -> None:
    """RunRequest should reject an empty prompt."""
    with pytest.raises(ValidationError):
        RunRequest(prompt="")


def test_run_response_serializes_to_json() -> None:
    """RunResponse should serialize to JSON-compatible output."""
    response = RunResponse(run_id="run-1", status=RunStatus.COMPLETED)
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "run_id": "run-1",
        "status": "completed",
        "contract_version": CONTRACT_VERSION,
    }


def test_run_status_values() -> None:
    """RunStatus enum should expose expected values."""
    assert RunStatus.PENDING == "pending"
    assert RunStatus.RUNNING == "running"
    assert RunStatus.WAITING_FOR_APPROVAL == "waiting_for_approval"
    assert RunStatus.COMPLETED == "completed"
    assert RunStatus.CANCELLED == "cancelled"
    assert RunStatus.FAILED == "failed"


# ============================================================
# END: Run Contract Tests
# ============================================================


# ============================================================
# BEGIN: Capability Contract Tests
# ============================================================


def test_capabilities_response_serializes_to_json() -> None:
    """CapabilitiesResponse should serialize with version and application."""
    response = CapabilitiesResponse(
        application="AVA",
        capabilities={CapabilityName.HEALTH: True, CapabilityName.RUNS: False},
    )
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "contract_version": CONTRACT_VERSION,
        "application": "AVA",
        "capabilities": {"health": True, "runs": False},
    }


def test_capability_names_are_stable_strings() -> None:
    """CapabilityName values should be stable lowercase strings."""
    assert CapabilityName.HEALTH == "health"
    assert CapabilityName.RUNS == "runs"
    assert CapabilityName.STREAMING == "streaming"
    assert CapabilityName.TOOL_CALLING == "tool_calling"
    assert CapabilityName.LOCAL_MODEL == "local_model"


# ============================================================
# END: Capability Contract Tests
# ============================================================


# ============================================================
# BEGIN: Event Contract Tests
# ============================================================


def test_run_event_serializes_to_json() -> None:
    """RunEvent should serialize to a JSON-compatible envelope."""
    event = RunEvent(
        event_id="evt-1",
        run_id="run-1",
        event_type=EventType.RUN_STARTED,
        payload={"source": "test"},
    )
    payload = event.model_dump(mode="json")
    json.dumps(payload)  # must not raise
    assert payload["event_id"] == "evt-1"
    assert payload["run_id"] == "run-1"
    assert payload["event_type"] == "run_started"
    assert payload["payload"] == {"source": "test"}
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["timestamp"].endswith("Z") or "+00:00" in payload["timestamp"]


def test_event_types_cover_run_lifecycle() -> None:
    """EventType should cover the run lifecycle states."""
    assert EventType.RUN_STARTED == "run_started"
    assert EventType.RUN_COMPLETED == "run_completed"
    assert EventType.RUN_CANCELLED == "run_cancelled"
    assert EventType.RUN_FAILED == "run_failed"
    assert EventType.APPROVAL_REQUESTED == "approval_requested"
    assert EventType.DOCUMENT_CHANGE_PROPOSED == "document_change_proposed"


def test_run_event_payload_rejects_non_json_safe_values() -> None:
    """RunEvent.payload must reject values that are not JSON-safe."""
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        RunEvent(
            event_id="evt-1",
            run_id="run-1",
            event_type=EventType.RUN_STARTED,
            payload={"started_at": datetime.now(UTC)},
        )


# ============================================================
# END: Event Contract Tests
# ============================================================


# ============================================================
# BEGIN: Error Contract Tests
# ============================================================


def test_error_response_serializes_to_json() -> None:
    """ErrorResponse should serialize with category, code, and version."""
    error = ErrorResponse(
        error_code="run_failed",
        category=ErrorCategory.AGENT,
        message="The agent could not complete the run.",
        recoverable=True,
        details={"stage": "generation"},
    )
    payload = error.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["error_code"] == "run_failed"
    assert payload["category"] == "agent"
    assert payload["recoverable"] is True
    assert payload["details"] == {"stage": "generation"}
    assert payload["contract_version"] == CONTRACT_VERSION


def test_error_response_details_accept_structured_json() -> None:
    """ErrorResponse.details should accept nested JSON-safe structures."""
    error = ErrorResponse(
        error_code="limit_exceeded",
        category=ErrorCategory.VALIDATION,
        message="Request out of range.",
        details={"retry_after_seconds": 30, "bounds": {"minimum": 0, "maximum": 2}},
    )
    payload = error.model_dump(mode="json")
    json.dumps(payload)  # must not raise
    assert payload["details"] == {
        "retry_after_seconds": 30,
        "bounds": {"minimum": 0, "maximum": 2},
    }


def test_error_details_reject_non_json_safe_values() -> None:
    """ErrorResponse.details must reject non-JSON-safe values."""
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        ErrorResponse(
            error_code="internal_error",
            category=ErrorCategory.INTERNAL,
            message="Bad detail.",
            details={"timestamp": datetime.now(UTC)},
        )


def test_error_category_values() -> None:
    """ErrorCategory should expose expected values."""
    assert ErrorCategory.VALIDATION == "validation"
    assert ErrorCategory.CONFIGURATION == "configuration"
    assert ErrorCategory.UNAVAILABLE == "unavailable"
    assert ErrorCategory.TIMEOUT == "timeout"
    assert ErrorCategory.PROVIDER == "provider"
    assert ErrorCategory.INTERNAL == "internal"


# ============================================================
# END: Error Contract Tests
# ============================================================


# ============================================================
# BEGIN: Model Contract Tests
# ============================================================


def test_model_request_serializes_to_json() -> None:
    """ModelRequest should serialize with typed messages and version."""
    request = ModelRequest(
        messages=[ModelMessage(role="user", content="Summarize the document")],
        temperature=0.2,
        max_output_tokens=256,
    )
    payload = request.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["messages"] == [
        {"role": "user", "content": "Summarize the document"}
    ]
    assert payload["temperature"] == 0.2
    assert payload["max_output_tokens"] == 256
    assert payload["contract_version"] == CONTRACT_VERSION


def test_model_response_serializes_to_json() -> None:
    """ModelResponse should serialize with content, model id, and version."""
    response = ModelResponse(content="Summary.", model_id="mock-model")
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "content": "Summary.",
        "model_id": "mock-model",
        "contract_version": CONTRACT_VERSION,
    }


def test_model_info_serializes_to_json() -> None:
    """ModelInfo should serialize with provider and model identity."""
    info = ModelInfo(
        provider_name="mock",
        model_id="mock-model",
        display_name="Mock Model",
        context_limit=4096,
    )
    payload = info.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["provider_name"] == "mock"
    assert payload["model_id"] == "mock-model"
    assert payload["context_limit"] == 4096


def test_model_provider_health_serializes_to_json() -> None:
    """ModelProviderHealth should carry available flag, status, and message."""
    health = ModelProviderHealth(
        available=False,
        status=ModelProviderHealthStatus.MODEL_NOT_LOADED,
        message="Model weights not loaded.",
    )
    payload = health.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["available"] is False
    assert payload["status"] == "model_not_loaded"
    assert payload["message"] == "Model weights not loaded."


def test_model_provider_health_status_values() -> None:
    """ModelProviderHealthStatus should expose expected values."""
    assert ModelProviderHealthStatus.HEALTHY == "healthy"
    assert ModelProviderHealthStatus.DEGRADED == "degraded"
    assert ModelProviderHealthStatus.UNAVAILABLE == "unavailable"
    assert ModelProviderHealthStatus.RUNTIME_UNAVAILABLE == "runtime_unavailable"
    assert ModelProviderHealthStatus.MODEL_NOT_LOADED == "model_not_loaded"
    assert ModelProviderHealthStatus.AUTHENTICATION_FAILED == "authentication_failed"
    assert ModelProviderHealthStatus.CONFIGURATION_INVALID == "configuration_invalid"


# ============================================================
# END: Model Contract Tests
# ============================================================