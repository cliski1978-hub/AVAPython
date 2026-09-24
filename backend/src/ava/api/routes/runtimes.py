from fastapi import APIRouter, Request

from ava.contracts.responses import RuntimeDiscoveryResponse
from ava.services.runtime_discovery_service import RuntimeDiscoveryService

router = APIRouter(tags=["runtimes"])


@router.get("/runtimes", response_model=RuntimeDiscoveryResponse)
def list_runtimes(request: Request) -> RuntimeDiscoveryResponse:
    service: RuntimeDiscoveryService = request.app.state.runtime_discovery_service
    return service.discover()
