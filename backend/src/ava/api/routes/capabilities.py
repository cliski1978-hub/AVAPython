"""Capability check routes.

Kept deliberately thin; the response contract lives in
ava.contracts.responses and the capability snapshot is produced by the
capability service.
"""

from fastapi import APIRouter, Request

from ava.contracts.responses import CapabilitiesResponse
from ava.services.capability_service import CapabilityService

router = APIRouter(tags=["capabilities"])


# ============================================================
# BEGIN: Capabilities Endpoint
# ============================================================


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(request: Request) -> CapabilitiesResponse:
    """Return the capabilities that currently exist.

    Reads the capability service from app state. This route contains no
    business logic — it delegates to the service and returns the contract.
    """
    service: CapabilityService = request.app.state.capability_service
    return service.get_capabilities()


# ============================================================
# END: Capabilities Endpoint
# ============================================================
