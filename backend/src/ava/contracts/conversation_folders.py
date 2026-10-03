"""Public contracts for AVA conversation folders."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ava.contracts.version import CONTRACT_VERSION


class _ConversationFolderNameRequest(BaseModel):
    """Shared nonblank-name validation for folder write contracts."""

    name: str

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        """Reject empty and whitespace-only names; normalization is a service concern."""
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class CreateConversationFolderRequest(_ConversationFolderNameRequest):
    """Request contract for creating a conversation folder."""

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class UpdateConversationFolderRequest(_ConversationFolderNameRequest):
    """Request contract for renaming a conversation folder."""

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ConversationFolderResponse(BaseModel):
    """Public snapshot of a flat organizational conversation folder."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ConversationFolderListResponse(BaseModel):
    folders: list[ConversationFolderResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
