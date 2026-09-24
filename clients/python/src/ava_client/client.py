"""HTTP client for the AVA backend."""

from typing import Self

import httpx
from httpx import Client, Response

from ava_client.models import (
    CapabilitiesResponse,
    HealthResponse,
    ModelDiscoveryResponse,
    ModelProviderDiscoveryResponse,
    WorkspaceDiscoveryResponse,
)

# ============================================================
# BEGIN: AVA Client
# ============================================================


class AvaClient:
    """Thin HTTP client for the AVA backend API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Construct the client with a base URL.

        Args:
            base_url: The root URL of the AVA backend.
            transport: An optional httpx transport (e.g. a mock transport in
                tests). When omitted a real connection is used.
        """
        self._client = Client(
            base_url=base_url.rstrip("/"), timeout=10.0, transport=transport
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        """Support use as a context manager."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the client on context manager exit."""
        self.close()

    def health(self) -> HealthResponse:
        """Fetch the backend health status.

        Returns:
            A HealthResponse describing the backend state.
        """
        response: Response = self._client.get("/health")
        response.raise_for_status()
        return HealthResponse.model_validate(response.json())

    def capabilities(self) -> CapabilitiesResponse:
        """Fetch the current backend capability snapshot.

        Returns:
            A CapabilitiesResponse describing what currently exists.
        """
        response: Response = self._client.get("/capabilities")
        response.raise_for_status()
        return CapabilitiesResponse.model_validate(response.json())

    def model_providers(self) -> ModelProviderDiscoveryResponse:
        """Fetch the discovered model providers with model info and health.

        Returns:
            A ModelProviderDiscoveryResponse describing available providers.
        """
        response: Response = self._client.get("/model-providers")
        response.raise_for_status()
        return ModelProviderDiscoveryResponse.model_validate(response.json())

    def list_models(self) -> ModelDiscoveryResponse:
        """Fetch the read-only configured-model catalog.

        The response contains public metadata only; provider-native names,
        endpoints, credentials, and permissions are not exposed.
        """
        response: Response = self._client.get("/models")
        response.raise_for_status()
        return ModelDiscoveryResponse.model_validate(response.json())

    def get_workspaces(self) -> WorkspaceDiscoveryResponse:
        """Fetch the discovered AVA workspaces as safe public metadata.

        Returns:
            A WorkspaceDiscoveryResponse listing workspace id, display name,
            and kind only — never host paths or internal security details.
        """
        response: Response = self._client.get("/workspaces")
        response.raise_for_status()
        return WorkspaceDiscoveryResponse.model_validate(response.json())


# ============================================================
# END: AVA Client
# ============================================================
