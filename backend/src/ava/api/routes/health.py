"""Health check routes.

Kept deliberately thin; the response contract lives in
ava.contracts.responses, not here.
"""

from fastapi import APIRouter, Request

from ava.contracts.responses import HealthResponse, HealthStatus
from ava.core.application import Application

router = APIRouter(tags=["health"])


# ============================================================
# BEGIN: Health Endpoint
# ============================================================


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return the application liveness status.

    This endpoint currently serves as a simple liveness check: it confirms
    the API process is running and returns AVA's configured application
    identity. It does not yet perform dependency or provider readiness
    checks. The route contains no business logic — it returns the contract.
    """
    application: Application = request.app.state.application
    return HealthResponse(
        status=HealthStatus.HEALTHY,
        application=application.name(),
    )


# ============================================================
# END: Health Endpoint
# ============================================================
