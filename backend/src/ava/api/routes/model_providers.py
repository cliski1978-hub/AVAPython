"""Model provider discovery routes.

Kept deliberately thin; the response contract lives in
ava.contracts.responses and the discovery snapshot is produced by the
model provider discovery service. The route never imports a concrete provider
or reaches into the registry directly.
"""

from fastapi import APIRouter, Request

from ava.contracts.responses import ModelProviderDiscoveryResponse
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService

router = APIRouter(tags=["model-providers"])


# ============================================================
# BEGIN: Model Provider Discovery Endpoint
# ============================================================


@router.get("/model-providers", response_model=ModelProviderDiscoveryResponse)
async def list_model_providers(request: Request) -> ModelProviderDiscoveryResponse:
    """Return discovered model providers with model info and health.

    A dedicated resource endpoint rather than an extension of /capabilities:
    /capabilities reports application capability names (health, runs, ...),
    while this endpoint answers "what model providers are available, and are
    they healthy?" — a provider discovery snapshot. The route reads the
    discovery service from app state and contains no business logic.
    """
    service: ModelProviderDiscoveryService = request.app.state.model_provider_discovery_service
    return await service.discover()


# ============================================================
# END: Model Provider Discovery Endpoint
# ============================================================
