from ava_client.models import (
    CapabilitiesResponse,
    CapabilityName,
    HealthResponse,
    HealthStatus,
)


def test_client_models_validate_backend_contracts() -> None:
    health = HealthResponse.model_validate(
        {"status": "healthy", "application": "AVA", "contract_version": "v1"}
    )
    capabilities = CapabilitiesResponse.model_validate(
        {
            "application": "AVA",
            "contract_version": "v1",
            "capabilities": {"health": True, "runs": False},
        }
    )

    assert health.status is HealthStatus.HEALTHY
    assert capabilities.capabilities[CapabilityName.HEALTH] is True
