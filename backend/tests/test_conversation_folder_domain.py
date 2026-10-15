"""Phase 5.53 conversation folder domain and contract tests."""

from dataclasses import fields
from datetime import UTC, datetime
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from ava.contracts import (
    ConversationFolderResponse,
    CreateConversationFolderRequest,
    UpdateConversationFolderRequest,
)
from ava.contracts.conversations import ConversationResponse
from ava.contracts.version import CONTRACT_VERSION
from ava.repositories import ConversationFolderRecord, ConversationRecord


def test_folder_record_is_a_minimal_stable_identity_snapshot() -> None:
    created_at = datetime(2026, 10, 1, tzinfo=UTC)
    updated_at = datetime(2026, 10, 2, tzinfo=UTC)
    folder = ConversationFolderRecord(
        id="folder-1",
        name="Planning",
        created_at=created_at,
        updated_at=updated_at,
    )

    assert [field.name for field in fields(folder)] == [
        "id",
        "name",
        "created_at",
        "updated_at",
        "owner_principal_ref",
        "owner_tenant_ref",
    ]
    assert (folder.id, folder.name, folder.created_at, folder.updated_at) == (
        "folder-1",
        "Planning",
        created_at,
        updated_at,
    )


def test_folder_response_matches_the_public_snapshot_shape() -> None:
    response = ConversationFolderResponse(
        id="folder-1",
        name="Planning",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        updated_at=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert set(response.model_dump()) == {
        "id",
        "name",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert set(ConversationFolderResponse.model_fields) == {
        "id",
        "name",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert response.contract_version == CONTRACT_VERSION


@pytest.mark.parametrize(
    "request_type",
    [CreateConversationFolderRequest, UpdateConversationFolderRequest],
)
def test_folder_write_contracts_reject_blank_names(request_type: type) -> None:
    assert request_type(name="Research").name == "Research"
    # Whitespace around a nonblank name is preserved for the future write
    # service to normalize, following ConversationService title semantics.
    assert request_type(name="  Research  ").name == "  Research  "
    with pytest.raises(ValidationError):
        request_type(name="")
    with pytest.raises(ValidationError):
        request_type(name=" \t\n ")


def test_folder_contracts_allow_duplicate_display_names() -> None:
    first = CreateConversationFolderRequest(name="Research")
    second = CreateConversationFolderRequest(name="Research")

    assert first.name == second.name


def test_folder_contract_fields_stay_flat_and_minimal() -> None:
    expected = {"name", "contract_version"}
    assert set(CreateConversationFolderRequest.model_fields) == expected
    assert set(UpdateConversationFolderRequest.model_fields) == expected


def test_conversation_keeps_a_nullable_folder_id_without_embedding_a_folder() -> None:
    hints = get_type_hints(ConversationRecord)
    assert hints["folder_id"] == str | None
    assert "folder" not in hints

    now = datetime(2026, 10, 1, tzinfo=UTC)
    record = ConversationRecord(
        conversation_id="conversation-1",
        title="Research",
        created_at=now,
        updated_at=now,
        folder_id="folder-1",
    )
    response = ConversationResponse(
        conversation_id=record.conversation_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        folder_id=record.folder_id,
    )

    assert response.folder_id == "folder-1"
    assert "folder" not in ConversationResponse.model_fields
    assert ConversationRecord(
        conversation_id="conversation-2",
        title="Unfiled",
        created_at=now,
        updated_at=now,
        folder_id=None,
    ).folder_id is None
