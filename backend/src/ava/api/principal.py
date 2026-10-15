"""HTTP authentication adapter for AVA-owned verified-principal contracts."""

import os
from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status

from ava.contracts.security_identity import (
    DenyPrincipalValidity,
    PrincipalResolution,
    PrincipalResolutionStatus,
    PrincipalValidityPort,
    VerifiedPrincipal,
)
from ava.services.project_service import ProjectNotFoundError


class HttpPrincipalResolverPort(Protocol):
    """Infrastructure adapter that validates HTTP evidence server-side."""

    def resolve(self, request: Request) -> PrincipalResolution:
        """Return a verified identity, an authentication denial, or unavailable."""
        ...


class UnavailableHttpPrincipalResolver:
    """No identity provider is configured; never trusts local origin or headers."""

    def resolve(self, request: Request) -> PrincipalResolution:
        del request
        return PrincipalResolution(status=PrincipalResolutionStatus.UNAVAILABLE)


def principal_is_current(request: Request, principal: VerifiedPrincipal) -> bool:
    """Recheck session status and absolute expiry for a long-lived request."""
    if principal.valid_until is not None and principal.valid_until <= datetime.now(UTC):
        return False
    validity: PrincipalValidityPort = getattr(request.app.state, "principal_validity", DenyPrincipalValidity())
    try:
        return validity.is_current(principal.principal_ref, principal.authentication_context_ref) is True
    except Exception:
        return False


async def require_verified_principal(request: Request) -> VerifiedPrincipal:
    """FastAPI dependency for routes that require authenticated identity."""
    resolver: HttpPrincipalResolverPort = request.app.state.http_principal_resolver
    try:
        resolution = resolver.resolve(request)
    except Exception as exc:
        # Do not log the Request or exception: either may retain bearer material.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted authentication is unavailable.",
        ) from exc
    if resolution.status == PrincipalResolutionStatus.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted authentication is not configured.",
        )
    if resolution.status != PrincipalResolutionStatus.AUTHENTICATED or resolution.principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified identity is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = resolution.principal
    if not principal_is_current(request, principal):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The verified session is no longer valid.")
    return principal


async def require_conversation_owner(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> VerifiedPrincipal:
    """Require identity on Conversation routes and hide foreign/legacy records."""
    conversation_id = request.path_params.get("conversation_id")
    if conversation_id is None:
        return principal
    access = getattr(request.app.state, "conversation_access", None)
    try:
        allowed = access is not None and access.can_access(
            principal.principal_ref, principal.tenant_ref, str(conversation_id)
        ) is True
    except Exception:
        allowed = False
    if not allowed:
        # Use the same response for missing, legacy ownerless, foreign, and
        # cross-tenant Conversations so callers cannot enumerate identities.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.")
    return principal


async def require_project_owner(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> VerifiedPrincipal:
    """Require the verified principal to own any Project named in the route."""
    project_id = request.path_params.get("project_id")
    if project_id is None:
        return principal
    service = getattr(request.app.state, "project_service", None)
    try:
        project = service.get_project(str(project_id)) if service is not None else None
    except ProjectNotFoundError:
        # Let the route return its stable not-found response for absent IDs.
        return principal
    except Exception:
        project = None
    if project is None or (
        project.owner_principal_ref != principal.principal_ref or project.owner_tenant_ref != principal.tenant_ref
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project was not found.")
    return principal


async def require_core_prompt_admin(
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> VerifiedPrincipal:
    """Require an explicitly configured principal for global CORE mutations."""
    configured = os.environ.get("AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    if principal.principal_ref not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CORE prompt administration is unavailable.")
    return principal


async def require_attachment_owner(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> VerifiedPrincipal:
    """Scope direct attachment reads to their owning Conversation when linked."""
    attachment_id = request.path_params.get("attachment_id")
    service = getattr(request.app.state, "attachment_service", None)
    record = service.get_attachment(str(attachment_id)) if attachment_id is not None and service is not None else None
    owner_type = getattr(record, "owner_type", None)
    owner_id = getattr(record, "owner_id", None)
    if owner_type is None or owner_id is None:
        if attachment_id is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment was not found.")
        return principal
    owner_value = getattr(owner_type, "value", owner_type)
    conversation_id = str(owner_id) if owner_value == "conversation" else None
    if owner_value == "message":
        persistence = getattr(request.app.state, "persistence", None)
        message_repository = getattr(persistence, "message_repository", None)
        message = message_repository.get(str(owner_id)) if message_repository is not None else None
        conversation_id = getattr(message, "conversation_id", None)
    if conversation_id is not None:
        access = getattr(request.app.state, "conversation_access", None)
        try:
            allowed = access is not None and access.can_access(
                principal.principal_ref, principal.tenant_ref, str(conversation_id)
            ) is True
        except Exception:
            allowed = False
        if not allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment was not found.")
    return principal
