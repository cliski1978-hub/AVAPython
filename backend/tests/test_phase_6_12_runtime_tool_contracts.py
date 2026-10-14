"""Phase 6.12 provider-neutral tool-call contract tests."""

import json

from ava.contracts.models import ModelMessage, ModelRequest, ModelResponse
from ava.models.providers.openai_compatible.provider import (
    _from_chat_completion_response,
    _to_chat_completion_payload,
)


def test_model_request_carries_normalized_tool_schemas_and_tool_replies() -> None:
    """Tool schemas and call replies stay in AVA-owned provider contracts."""
    assert "tools" in ModelRequest.model_fields
    assert "tool_calls" in ModelResponse.model_fields
    assert "tool_calls" in ModelMessage.model_fields
    assert "tool_call_id" in ModelMessage.model_fields


def test_model_tool_call_round_trips_without_provider_sdk_values() -> None:
    from ava.contracts.models import ModelToolCall, ModelToolDefinition

    request = ModelRequest(
        messages=[ModelMessage(role="user", content="Read a file")],
        tools=[ModelToolDefinition(
            name="workspace.read",
            description="Read a workspace file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )],
    )
    assert request.model_dump(mode="json")["tools"][0]["name"] == "workspace.read"
    assert ModelResponse(
        content="",
        model_id="test",
        tool_calls=[ModelToolCall(id="call-1", name="workspace.read", arguments='{"path":"a.txt"}')],
    ).tool_calls[0].arguments == '{"path":"a.txt"}'


def test_openai_compatible_adapter_translates_structured_tools_and_calls() -> None:
    from ava.contracts.models import ModelToolDefinition

    request = ModelRequest(
        messages=[ModelMessage(role="user", content="Read")],
        tools=[ModelToolDefinition(
            name="workspace.read", description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )],
    )
    payload = _to_chat_completion_payload(request, "model")
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "workspace.read",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }]

    response = _from_chat_completion_response({
        "model": "model",
        "choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call-1", "type": "function", "function": {
                "name": "workspace.read", "arguments": '{"path":"a.txt"}',
            }}],
        }}],
    }, "fallback")
    assert response.content == ""
    assert response.tool_calls[0].name == "workspace.read"
    assert json.loads(response.tool_calls[0].arguments) == {"path": "a.txt"}
