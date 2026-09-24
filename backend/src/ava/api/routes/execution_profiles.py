from fastapi import APIRouter, Request

from ava.contracts.responses import ExecutionProfileDiscoveryResponse
from ava.services.execution_profile_service import ExecutionProfileService

router = APIRouter(tags=["execution-profiles"])
@router.get("/execution-profiles", response_model=ExecutionProfileDiscoveryResponse)
def list_execution_profiles(request: Request) -> ExecutionProfileDiscoveryResponse:
    service: ExecutionProfileService = request.app.state.execution_profile_service
    return service.discover()
