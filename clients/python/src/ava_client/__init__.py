"""AVA Python client library.

Lightweight client for communicating with the AVA backend API.
Intended for Databricks notebooks, Python scripts, automation, and testing
clients in later phases.
"""

from ava_client.client import AvaClient
from ava_client.models import (
    CapabilitiesResponse,
    CapabilityName,
    HealthResponse,
    HealthStatus,
    ModelCapabilities,
    ModelDiscoveryResponse,
    ModelHostingMode,
    ModelInfo,
    ModelProviderDiscoveryItem,
    ModelProviderDiscoveryResponse,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelQualificationInfo,
    QualificationStatus,
)

__all__ = [
    "AvaClient",
    "CapabilitiesResponse",
    "CapabilityName",
    "HealthResponse",
    "HealthStatus",
    "ModelCapabilities",
    "ModelDiscoveryResponse",
    "ModelHostingMode",
    "ModelInfo",
    "ModelProviderDiscoveryItem",
    "ModelProviderDiscoveryResponse",
    "ModelProviderHealth",
    "ModelProviderHealthStatus",
    "ModelQualificationInfo",
    "QualificationStatus",
]
__version__ = "0.1.0"
