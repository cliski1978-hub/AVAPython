"""Workspace discovery route.

Kept deliberately thin; the response contract lives in ava.contracts.responses
and the discovery snapshot is produced by the workspace discovery service. The
route never reaches into the registry or touches workspace internals directly.
"""

from fastapi import APIRouter, Request

from ava.contracts.responses import WorkspaceDiscoveryResponse
from ava.services.workspace_discovery_service import WorkspaceDiscoveryService

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces", response_model=WorkspaceDiscoveryResponse)
def list_workspaces(request: Request) -> WorkspaceDiscoveryResponse:
    """Return the network-safe metadata for AVA-approved workspaces.

    Exposes only workspace identity (id, display name, kind). Host filesystem
    paths, resolved root paths, runtime bindings, and internal security
    details are never part of this endpoint.
    """
    service: WorkspaceDiscoveryService = request.app.state.workspace_discovery_service
    return service.discover()