"""Phase 5.66 CORE prompt definition and contract coverage."""

from dataclasses import fields
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ava.contracts import (
    CorePromptCategory,
    CorePromptResponse,
    CreateCorePromptRequest,
    UpdateCorePromptRequest,
)
from ava.contracts.version import CONTRACT_VERSION
from ava.repositories import CorePromptRecord


def test_core_prompt_record_is_an_immutable_definition_snapshot() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    text = "# Guidance\n\n- Preserve  indentation\n- 日本語 → 🧭\n"
    record = CorePromptRecord(
        id="cp_opaque-id",
        name="Architecture Guardian",
        description=None,
        prompt_text=text,
        category=CorePromptCategory.ARCHITECTURE,
        is_enabled=True,
        created_at=now,
        updated_at=now,
    )

    assert [field.name for field in fields(record)] == [
        "id",
        "name",
        "description",
        "prompt_text",
        "category",
        "is_enabled",
        "created_at",
        "updated_at",
    ]
    assert record.prompt_text == text
    assert record.created_at.tzinfo is UTC
    assert record.updated_at.tzinfo is UTC


def test_core_prompt_category_values_are_canonical_and_lowercase() -> None:
    assert [category.value for category in CorePromptCategory] == [
        "core",
        "engineering",
        "research",
        "safety",
        "style",
        "tool_use",
        "architecture",
        "organization",
        "general",
    ]


def test_create_contract_validates_nonblank_name_and_prompt_without_normalizing() -> None:
    prompt_text = "  # Exact text\n\n- 東京\n"
    request = CreateCorePromptRequest(
        name="  AVA Core  ",
        description=None,
        prompt_text=prompt_text,
        category=CorePromptCategory.CORE,
    )
    assert request.name == "  AVA Core  "
    assert request.description is None
    assert request.prompt_text == prompt_text
    with pytest.raises(ValidationError, match="name must not be blank"):
        CreateCorePromptRequest(name=" \t\n", prompt_text="valid", category="core")
    with pytest.raises(ValidationError, match="prompt_text must not be blank"):
        CreateCorePromptRequest(name="Valid", prompt_text=" \t\n", category="core")
    with pytest.raises(ValidationError):
        CreateCorePromptRequest(name="Valid", prompt_text="valid", category="not-a-category")


def test_core_prompt_update_preserves_omitted_description_and_accepts_explicit_null() -> None:
    omitted = UpdateCorePromptRequest(
        name="AVA Core",
        prompt_text="new text",
        category=CorePromptCategory.CORE,
    )
    cleared = UpdateCorePromptRequest(
        name="AVA Core",
        description=None,
        prompt_text="new text",
        category=CorePromptCategory.CORE,
    )
    assert "description" not in omitted.model_fields_set
    assert cleared.description is None
    assert "description" in cleared.model_fields_set


def test_core_prompt_response_serializes_all_definition_fields() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    response = CorePromptResponse(
        id="cp_1",
        name="Research Assistant",
        description=None,
        prompt_text="Ask for evidence.",
        category=CorePromptCategory.RESEARCH,
        is_enabled=False,
        created_at=now,
        updated_at=now,
    )
    assert set(response.model_dump()) == {
        "id",
        "name",
        "description",
        "prompt_text",
        "category",
        "is_enabled",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert response.model_dump(mode="json")["category"] == "research"
    assert response.model_dump()["is_enabled"] is False
    assert response.contract_version == CONTRACT_VERSION


def test_duplicate_display_names_are_valid_and_definition_has_no_scope_or_policy_fields() -> None:
    request_data = {"name": "Research", "prompt_text": "Be precise.", "category": "research"}
    assert CreateCorePromptRequest(**request_data).name == CreateCorePromptRequest(**request_data).name
    forbidden = {
        "priority",
        "scope_type",
        "scope_id",
        "project_id",
        "folder_id",
        "conversation_id",
        "provider",
        "model",
        "runtime",
        "message_role",
        "inherit",
        "override",
    }
    record_fields = {field.name for field in fields(CorePromptRecord)}
    response_fields = set(CorePromptResponse.model_fields)
    assert forbidden.isdisjoint(record_fields)
    assert forbidden.isdisjoint(response_fields)
