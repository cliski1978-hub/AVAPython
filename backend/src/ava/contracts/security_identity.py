"""Provider-neutral verified identity and security authority contracts.

These values describe the result of server-side authentication. They are never
accepted from API request bodies and contain no credentials or provider SDK
objects.
"""

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Protocol, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrincipalActorType(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


class PrincipalResolutionStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    UNAVAILABLE = "unavailable"


class VerifiedPrincipal(BaseModel):
    """Minimal identity evidence returned only by a trusted resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_provider: str = Field(strict=True, min_length=1, max_length=512)
    subject: str = Field(strict=True, min_length=1, max_length=512)
    tenant_ref: str | None = Field(default=None, strict=True, min_length=1, max_length=512)
    actor_type: PrincipalActorType
    authentication_context: str = Field(strict=True, min_length=1, max_length=128)
    authentication_context_ref: str = Field(strict=True, min_length=32, max_length=128)
    authenticated_at: datetime
    valid_until: datetime | None = None
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)

    @field_validator("authenticated_at", "valid_until")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("authentication timestamps must be timezone-aware")
        return value

    @field_validator("identity_provider")
    @classmethod
    def reject_credentials_in_namespace(cls, value: str) -> str:
        if any(char.isspace() for char in value):
            raise ValueError("identity provider namespace is invalid")
        if "://" in value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("identity provider namespace is invalid")
        elif "@" in value or "?" in value or "#" in value:
            raise ValueError("identity provider namespace is invalid")
        return value

    @field_validator("authentication_context")
    @classmethod
    def safe_authentication_context(cls, value: str) -> str:
        normalized = value.lower()
        if (
            not value.replace("_", "").replace("-", "").isalnum()
            or any(term in normalized for term in ("password", "secret", "credential", "token", "api_key"))
        ):
            raise ValueError("authentication context must be a safe identifier")
        return value

    @field_validator("authentication_context_ref")
    @classmethod
    def require_opaque_authentication_reference(cls, value: str) -> str:
        """Store only a fixed-width opaque digest, never a provider session credential."""
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("authentication context reference must be an opaque lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def valid_lifetime(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.authenticated_at:
            raise ValueError("authentication validity must end after authentication")
        return self

    @property
    def principal_ref(self) -> str:
        """Stable opaque reference derived from verified issuer and subject."""
        material = f"{self.identity_provider}\0{self.subject}".encode()
        return sha256(material).hexdigest()


class PrincipalResolution(BaseModel):
    """Authentication result with explicit unauthenticated/unavailable states."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: PrincipalResolutionStatus
    principal: VerifiedPrincipal | None = None

    @model_validator(mode="after")
    def status_matches_principal(self) -> Self:
        if (self.status == PrincipalResolutionStatus.AUTHENTICATED) != (self.principal is not None):
            raise ValueError("only authenticated resolution may contain a principal")
        return self


class PrincipalValidityPort(Protocol):
    """Revalidate an authentication session for background authority checks."""

    def is_current(self, principal_ref: str, authentication_context_ref: str) -> bool:
        """Return true only while the exact verified session remains current."""
        ...


class ConversationAccessPort(Protocol):
    """Trusted owner check for legacy conversation context linked to a Run."""

    def can_access(self, principal_ref: str, tenant_ref: str | None, conversation_id: str) -> bool:
        """Return true only when the authenticated principal owns this conversation."""
        ...


class DenyConversationAccess:
    """Legacy conversations have no owner field, so linked context denies by default."""

    def can_access(self, principal_ref: str, tenant_ref: str | None, conversation_id: str) -> bool:
        del principal_ref, tenant_ref, conversation_id
        return False


class DenyPrincipalValidity:
    """Default-deny session validity when no trusted provider is configured."""

    def is_current(self, principal_ref: str, authentication_context_ref: str) -> bool:
        del principal_ref, authentication_context_ref
        return False
