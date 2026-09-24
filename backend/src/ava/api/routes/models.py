"""Model catalog discovery routes.

Kept deliberately thin; the response contract lives in
ava.contracts.responses and the catalog snapshot is produced by the model
discovery service. The route never reaches into the registry directly and never
imports a concrete provider.
"""

from fastapi import APIRouter, Request

from ava.contracts.responses import ModelDiscoveryResponse
from ava.services.model_discovery_service import ModelDiscoveryService

router = APIRouter(tags=["models"])


# ============================================================
# BEGIN: Model Discovery Endpoint
# ============================================================


@router.get("/models", response_model=ModelDiscoveryResponse)
async def list_models(request: Request) -> ModelDiscoveryResponse:
    """Return the configured model catalog as read-only public metadata.

    A dedicated resource endpoint rather than an extension of
    /model-providers: /model-providers reports running provider adapters and
    their health, while /models reports the configured model catalog (stable
    identity, hosting placement, declared capabilities, enabled state). It is
    registry-backed and contacts no provider or endpoint.
    """
    service: ModelDiscoveryService = request.app.state.model_discovery_service
    return service.discover()


# ============================================================
# END: Model Discovery Endpoint
# ============================================================
