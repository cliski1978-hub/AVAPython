"""Contract tests.

Verify that AVA contracts are framework-neutral, JSON-compatible, and carry
the current contract version.
"""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ava.contracts.capabilities import CapabilityName
from ava.contracts.documents import (
    ContentFormat,
    DocumentRevisionListResponse,
    DocumentRevisionResponse,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.models import (
    ModelCapabilities,
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
    ModelProviderDiscoveryItem,
    ModelProviderDiscoveryResponse,
    RunResponse,
    RunStatus,
)
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
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


def test_run_request_rejects_whitespace_only_prompt() -> None:
    """RunRequest should reject prompts containing only whitespace."""
    with pytest.raises(ValidationError):
        RunRequest(prompt="   \n\t  ")


def test_run_response_serializes_to_json() -> None:
    """RunResponse should serialize to JSON-compatible output."""
    response = RunResponse(run_id="run-1", status=RunStatus.COMPLETED)
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "run_id": "run-1",
        "status": "completed",
        "contract_version": CONTRACT_VERSION,
        "execution_selection": None,
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


def test_model_capabilities_default_to_conservative_false() -> None:
    """ModelCapabilities defaults must be deterministic and conservative.

    Unsupported capabilities must not accidentally default to enabled.
    """
    capabilities = ModelCapabilities()
    payload = capabilities.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["chat"] is False
    assert payload["streaming"] is False
    assert payload["tool_calling"] is False
    assert payload["structured_output"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False
    assert payload["contract_version"] == CONTRACT_VERSION


def test_model_capabilities_can_enable_capabilities_independently() -> None:
    """Multiple capabilities can be enabled without enabling the rest."""
    capabilities = ModelCapabilities(
        chat=True,
        streaming=True,
        tool_calling=True,
    )
    payload = capabilities.model_dump()
    assert payload["chat"] is True
    assert payload["streaming"] is True
    assert payload["tool_calling"] is True
    assert payload["structured_output"] is False
    assert payload["vision"] is False
    assert payload["embeddings"] is False
    assert payload["reasoning"] is False
    assert payload["code_specialization"] is False


def test_model_capabilities_are_independent_of_each_other() -> None:
    """Enabling one capability must not implicitly enable unrelated ones."""
    capabilities = ModelCapabilities(tool_calling=True)
    assert capabilities.tool_calling is True
    assert capabilities.chat is False
    assert capabilities.streaming is False
    assert capabilities.structured_output is False
    assert capabilities.reasoning is False
    assert capabilities.vision is False

    vision_only = ModelCapabilities(vision=True)
    assert vision_only.vision is True
    assert vision_only.tool_calling is False
    assert vision_only.chat is False
    assert vision_only.embeddings is False
    assert vision_only.code_specialization is False


def test_model_capabilities_serialize_to_json() -> None:
    """ModelCapabilities must serialize to a JSON-safe, provider-neutral form."""
    capabilities = ModelCapabilities(chat=True, reasoning=True)
    payload = capabilities.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "chat": True,
        "streaming": False,
        "tool_calling": False,
        "structured_output": False,
        "vision": False,
        "embeddings": False,
        "reasoning": True,
        "code_specialization": False,
        "contract_version": CONTRACT_VERSION,
    }


def test_model_info_includes_capabilities() -> None:
    """ModelInfo should carry identity, context window, and capabilities."""
    info = ModelInfo(
        provider_name="mock",
        model_id="mock-model",
        display_name="Mock Model",
        context_limit=4096,
        capabilities=ModelCapabilities(chat=True, streaming=True),
    )
    payload = info.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["provider_name"] == "mock"
    assert payload["model_id"] == "mock-model"
    assert payload["display_name"] == "Mock Model"
    assert payload["context_limit"] == 4096
    assert payload["capabilities"]["chat"] is True
    assert payload["capabilities"]["streaming"] is True
    assert payload["capabilities"]["tool_calling"] is False
    assert payload["contract_version"] == CONTRACT_VERSION


def test_model_info_context_window_is_numeric_metadata() -> None:
    """Context window is a numeric model property, not a boolean capability."""
    capabilities = ModelCapabilities()
    info = ModelInfo(
        provider_name="mock",
        model_id="mock-model",
        context_limit=8192,
        capabilities=capabilities,
    )
    assert isinstance(info.context_limit, int)
    assert "context_limit" in info.model_dump(include={"context_limit", "capabilities"})
    assert "context_limit" not in ModelCapabilities.model_fields


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


# ============================================================
# BEGIN: Model Provider Discovery Contract Tests
# ============================================================


def test_model_provider_discovery_item_serializes_to_json() -> None:
    """ModelProviderDiscoveryItem should carry identity, model info, and health."""
    item = ModelProviderDiscoveryItem(
        provider_id="local",
        is_default=True,
        model_info=ModelInfo(provider_name="local", model_id="local-model"),
        health=ModelProviderHealth(
            available=True,
            status=ModelProviderHealthStatus.HEALTHY,
        ),
    )
    payload = item.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["provider_id"] == "local"
    assert payload["is_default"] is True
    assert payload["model_info"]["model_id"] == "local-model"
    assert payload["health"]["status"] == "healthy"
    assert payload["contract_version"] == CONTRACT_VERSION


def test_model_provider_discovery_response_serializes_with_empty_providers() -> None:
    """ModelProviderDiscoveryResponse serializes an empty provider list truthfully."""
    response = ModelProviderDiscoveryResponse(
        default_provider_id="corporate",
        providers=[],
    )
    payload = response.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "contract_version": CONTRACT_VERSION,
        "default_provider_id": "corporate",
        "providers": [],
    }


def test_model_provider_discovery_response_embeds_model_info_and_health() -> None:
    """Discovery should reuse ModelInfo and ModelProviderHealth without duplication."""
    response = ModelProviderDiscoveryResponse(
        default_provider_id="local",
        providers=[
            ModelProviderDiscoveryItem(
                provider_id="local",
                is_default=True,
                model_info=ModelInfo(
                    provider_name="local",
                    model_id="local-model",
                    context_limit=8192,
                ),
                health=ModelProviderHealth(
                    available=False,
                    status=ModelProviderHealthStatus.RUNTIME_UNAVAILABLE,
                ),
            )
        ],
    )
    payload = response.model_dump(mode="json")
    json.dumps(payload)  # must not raise
    provider = payload["providers"][0]
    assert provider["model_info"]["context_limit"] == 8192
    assert provider["model_info"]["provider_name"] == "local"
    assert provider["health"]["status"] == "runtime_unavailable"
    assert provider["health"]["available"] is False


# ============================================================
# END: Model Provider Discovery Contract Tests
# ============================================================


# ============================================================
# BEGIN: Runtime Contract Tests
# ============================================================


def test_runtime_capabilities_default_to_conservative_false() -> None:
    """RuntimeCapabilities defaults must be deterministic and conservative.

    An unsupported capability must not accidentally default to enabled.
    """
    capabilities = RuntimeCapabilities()
    payload = capabilities.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["tools"] is False
    assert payload["multi_agent"] is False
    assert payload["shell"] is False
    assert payload["filesystem"] is False
    assert payload["browser"] is False
    assert payload["code_execution"] is False
    assert payload["checkpointing"] is False
    assert payload["persistence"] is False
    assert payload["human_approval"] is False
    assert payload["parallel_execution"] is False
    assert payload["contract_version"] == CONTRACT_VERSION


def test_runtime_capabilities_can_enable_capabilities_independently() -> None:
    """Multiple runtime capabilities can be enabled without enabling the rest."""
    capabilities = RuntimeCapabilities(
        tools=True,
        filesystem=True,
        code_execution=True,
    )
    payload = capabilities.model_dump()
    assert payload["tools"] is True
    assert payload["filesystem"] is True
    assert payload["code_execution"] is True
    assert payload["shell"] is False
    assert payload["browser"] is False
    assert payload["multi_agent"] is False
    assert payload["persistence"] is False
    assert payload["parallel_execution"] is False


def test_runtime_capabilities_are_independent_of_each_other() -> None:
    """Enabling one capability must not implicitly enable unrelated ones."""
    capabilities = RuntimeCapabilities(tools=True)
    assert capabilities.tools is True
    assert capabilities.shell is False
    assert capabilities.filesystem is False
    assert capabilities.code_execution is False
    assert capabilities.multi_agent is False
    assert capabilities.parallel_execution is False

    multi_agent_only = RuntimeCapabilities(multi_agent=True)
    assert multi_agent_only.multi_agent is True
    assert multi_agent_only.parallel_execution is False
    assert multi_agent_only.tools is False
    assert multi_agent_only.shell is False
    assert multi_agent_only.filesystem is False
    assert multi_agent_only.code_execution is False


def test_runtime_capabilities_serialize_to_json() -> None:
    """RuntimeCapabilities must serialize to a JSON-safe, framework-neutral form."""
    capabilities = RuntimeCapabilities(tools=True, shell=True)
    payload = capabilities.model_dump()
    json.dumps(payload)  # must not raise
    assert payload == {
        "tools": True,
        "multi_agent": False,
        "shell": True,
        "filesystem": False,
        "browser": False,
        "code_execution": False,
        "checkpointing": False,
        "persistence": False,
        "human_approval": False,
        "parallel_execution": False,
        "contract_version": CONTRACT_VERSION,
    }


def test_runtime_info_includes_capabilities() -> None:
    """RuntimeInfo should carry identity and capabilities."""
    info = RuntimeInfo(
        runtime_id="native",
        display_name="AVA Native Runtime",
        capabilities=RuntimeCapabilities(tools=True, shell=True),
    )
    payload = info.model_dump()
    json.dumps(payload)  # must not raise
    assert payload["runtime_id"] == "native"
    assert payload["display_name"] == "AVA Native Runtime"
    assert payload["capabilities"]["tools"] is True
    assert payload["capabilities"]["shell"] is True
    assert payload["capabilities"]["browser"] is False
    assert payload["contract_version"] == CONTRACT_VERSION


def test_runtime_info_requires_runtime_id() -> None:
    """RuntimeInfo must require a runtime identifier."""
    with pytest.raises(ValidationError):
        RuntimeInfo()  # type: ignore[call-arg]


def test_runtime_info_display_name_is_optional() -> None:
    """RuntimeInfo display_name is optional; runtime_id suffices."""
    info = RuntimeInfo(runtime_id="native")
    payload = info.model_dump()
    assert payload["runtime_id"] == "native"
    assert payload["display_name"] is None


def test_runtime_and_model_capabilities_are_independent() -> None:
    """RuntimeCapabilities and ModelCapabilities are separate contracts.

    One should not alter or imply values in the other.
    """
    runtime_caps = RuntimeCapabilities(tools=True)
    model_caps = ModelCapabilities(tool_calling=True)

    # Runtime has tools but model does not
    assert runtime_caps.tools is True
    assert model_caps.tool_calling is True
    assert not hasattr(model_caps, "tools") or "tools" not in ModelCapabilities.model_fields
    assert not hasattr(runtime_caps, "tool_calling") or "tool_calling" not in RuntimeCapabilities.model_fields

    # Runtime without tools, model without tool calling
    runtime_empty = RuntimeCapabilities()
    model_empty = ModelCapabilities()
    assert runtime_empty.tools is False
    assert model_empty.tool_calling is False
    assert runtime_empty.contract_version == CONTRACT_VERSION
    assert model_empty.contract_version == CONTRACT_VERSION


# ============================================================
# END: Runtime Contract Tests
# ============================================================


# ============================================================
# BEGIN: Document Revision Contract Tests (Step 4.13.E)
# ============================================================


def _revision_payload() -> dict[str, object]:
    """Build the full wire payload for a DocumentRevisionResponse."""
    return {
        "revision_id": "rev-1",
        "document_id": "doc-1",
        "revision_number": 1,
        "title": "My Doc",
        "content": "<p>canonical html</p>",
        "content_format": "html",
        "created_at": "2026-01-01T00:00:00Z",
        "contract_version": CONTRACT_VERSION,
    }


def _make_revision_response() -> DocumentRevisionResponse:
    return DocumentRevisionResponse(
        revision_id="rev-1",
        document_id="doc-1",
        revision_number=1,
        title="My Doc",
        content="<p>canonical html</p>",
        content_format=ContentFormat.HTML,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_document_revision_response_serializes_to_json() -> None:
    """DocumentRevisionResponse serializes with all revision fields and version."""
    payload = _make_revision_response().model_dump(mode="json")
    json.dumps(payload)  # must not raise
    assert payload == _revision_payload()


def test_document_revision_response_requires_document_scoped_fields() -> None:
    """The revision contract carries identity, snapshot, and history fields."""
    revision = _make_revision_response()
    assert revision.revision_id == "rev-1"
    assert revision.document_id == "doc-1"
    assert revision.revision_number == 1
    assert revision.content_format is ContentFormat.HTML
    assert revision.title == "My Doc"
    assert revision.content == "<p>canonical html</p>"
    assert revision.created_at.tzinfo is not None
    assert revision.contract_version == CONTRACT_VERSION


def test_document_revision_response_revision_number_stays_numeric() -> None:
    """revision_number is an int sequence, never coerced to a string."""
    revision = _make_revision_response()
    assert isinstance(revision.revision_number, int)
    assert revision.model_dump()["revision_number"] == 1
    assert isinstance(revision.model_dump()["revision_number"], int)


def test_document_revision_response_exposes_no_persistence_only_fields() -> None:
    """No surrogate id, audit, restore, author, or parent fields leak."""
    revision = _make_revision_response()
    fields = set(DocumentRevisionResponse.model_fields)
    assert fields == {
        "revision_id",
        "document_id",
        "revision_number",
        "title",
        "content",
        "content_format",
        "created_at",
        "contract_version",
    }
    payload = revision.model_dump()
    assert "id" not in payload
    assert "author" not in payload
    assert "source" not in payload
    assert "parent_revision" not in payload
    assert "document_updated_at" not in payload


def test_document_revision_list_response_serializes_to_json() -> None:
    """DocumentRevisionListResponse carries document id and ordered revisions."""
    response = DocumentRevisionListResponse(
        document_id="doc-1",
        revisions=[_make_revision_response()],
    )
    payload = response.model_dump(mode="json")
    json.dumps(payload)  # must not raise
    assert payload == {
        "contract_version": CONTRACT_VERSION,
        "document_id": "doc-1",
        "revisions": [_revision_payload()],
    }


def test_document_revision_list_response_allows_empty_history() -> None:
    """A known document with no history serializes an empty revisions list."""
    response = DocumentRevisionListResponse(document_id="doc-1", revisions=[])
    payload = response.model_dump(mode="json")
    assert payload["revisions"] == []
    assert payload["document_id"] == "doc-1"
    assert payload["contract_version"] == CONTRACT_VERSION


def test_contract_version_is_independent_of_revision_number() -> None:
    """contract_version is the transport schema; revision_number is document history.

    A revision at sequence position N still carries the same transport
    contract_version as every other revision, and the transport version never
    changes as history advances.
    """
    first = DocumentRevisionResponse(
        revision_id="rev-1",
        document_id="doc-1",
        revision_number=1,
        title="T",
        content="<p>a</p>",
        content_format=ContentFormat.HTML,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = DocumentRevisionResponse(
        revision_id="rev-2",
        document_id="doc-1",
        revision_number=2,
        title="T",
        content="<p>b</p>",
        content_format=ContentFormat.HTML,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert first.revision_number == 1
    assert second.revision_number == 2
    assert first.contract_version == second.contract_version == CONTRACT_VERSION
    assert first.contract_version != str(first.revision_number)
    assert second.contract_version != str(second.revision_number)


# ============================================================
# END: Document Revision Contract Tests
# ============================================================
