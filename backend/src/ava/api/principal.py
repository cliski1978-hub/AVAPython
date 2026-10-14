"""HTTP authentication adapter for AVA-owned verified-principal contracts."""

from datetime import UTC, datetime
from typing import Protocol

from fastapi import HTTPException, Request, status

from ava.contracts.security_identity import (
    DenyPrincipalValidity,
    PrincipalResolution,
    PrincipalResolutionStatus,
    PrincipalValidityPort,
    VerifiedPrincipal,
)


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


def require_verified_principal(request: Request) -> VerifiedPrincipal:
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
