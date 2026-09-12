"""HTTP client for the AVA backend."""

from httpx import Client, Response

from ava_client.models import CapabilitiesResponse, HealthResponse

# ============================================================
# BEGIN: AVA Client
# ============================================================


class AvaClient:
    """Thin HTTP client for the AVA backend API."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        """Construct the client with a base URL.

        Args:
            base_url: The root URL of the AVA backend.
        """
        self._client = Client(base_url=base_url.rstrip("/"), timeout=10.0)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "AvaClient":
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


# ============================================================
# END: AVA Client
# ============================================================
