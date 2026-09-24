from ava_client.models import (
    CapabilitiesResponse,
    CapabilityName,
    HealthResponse,
    HealthStatus,
    ModelDiscoveryResponse,
    ModelHostingMode,
    ModelProviderDiscoveryResponse,
    ModelProviderHealthStatus,
    WorkspaceDiscoveryResponse,
    WorkspaceKind,
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


def test_client_models_validate_model_provider_discovery_contracts() -> None:
    response = ModelProviderDiscoveryResponse.model_validate(
        {
            "contract_version": "v1",
            "default_provider_id": "local",
            "providers": [
                {
                    "provider_id": "local",
                    "is_default": True,
                    "model_info": {
                        "provider_name": "local",
                        "model_id": "local-model",
                        "display_name": None,
                        "context_limit": None,
                        "capabilities": {
                            "chat": True,
                            "streaming": False,
                            "tool_calling": False,
                            "structured_output": False,
                            "vision": False,
                            "embeddings": False,
                            "reasoning": False,
                            "code_specialization": False,
                            "contract_version": "v1",
                        },
                        "contract_version": "v1",
                    },
                    "health": {
                        "available": True,
                        "status": "healthy",
                        "message": None,
                        "contract_version": "v1",
                    },
                    "contract_version": "v1",
                }
            ],
        }
    )

    item = response.providers[0]
    assert response.default_provider_id == "local"
    assert item.is_default is True
    assert item.health.status is ModelProviderHealthStatus.HEALTHY
    assert item.model_info.model_id == "local-model"
    assert item.model_info.capabilities.chat is True


def test_client_models_validate_catalog_qualification_metadata() -> None:
    response = ModelDiscoveryResponse.model_validate(
        {
            "contract_version": "v1",
            "models": [
                {
                    "provider_name": "local",
                    "model_id": "ava/local",
                    "capabilities": {"contract_version": "v1"},
                    "qualifications": [
                        {
                            "qualification_id": "native-tool-call",
                            "status": "pass",
                            "runtime_id": "native",
                            "task_class": "tool_calling",
                            "evidence_summary": "Observed native tool call.",
                            "measured_at": None,
                            "contract_version": "v1",
                        }
                    ],
                    "contract_version": "v1",
                }
            ],
        }
    )

    qualification = response.models[0].qualifications[0]
    assert qualification.status.value == "pass"
    assert qualification.runtime_id == "native"


def test_client_models_validate_workspace_discovery_contracts() -> None:
    response = WorkspaceDiscoveryResponse.model_validate(
        {
            "contract_version": "v1",
            "workspaces": [
                {"workspace_id": "temporary-test", "display_name": "Temporary Test", "kind": "local"},
                {"workspace_id": "project-test", "display_name": "Project Test", "kind": "local"},
            ],
        }
    )

    assert response.contract_version == "v1"
    assert [item.workspace_id for item in response.workspaces] == [
        "temporary-test",
        "project-test",
    ]
    assert [item.display_name for item in response.workspaces] == [
        "Temporary Test",
        "Project Test",
    ]
    assert all(item.kind is WorkspaceKind.LOCAL for item in response.workspaces)


def test_client_workspace_models_reject_unknown_path_fields() -> None:
    """Client workspace models ignore/never require internal host paths."""
    response = WorkspaceDiscoveryResponse.model_validate(
        {
            "contract_version": "v1",
            "workspaces": [
                {"workspace_id": "project-test", "display_name": "Project Test", "kind": "local"},
            ],
        }
    )

    item = response.workspaces[0]
    assert item.model_dump() == {
        "workspace_id": "project-test",
        "display_name": "Project Test",
        "kind": WorkspaceKind.LOCAL,
    }
    assert "root_path" not in item.model_dump()
    assert "local_path" not in item.model_dump()


def test_client_models_validate_catalog_discovery_contract() -> None:
    response = ModelDiscoveryResponse.model_validate(
        {
            "contract_version": "v1",
            "models": [{
                "provider_name": "local", "model_id": "ava/local", "display_name": "Local",
                "context_limit": None,
                "capabilities": {
                    "chat": True, "streaming": False, "tool_calling": True,
                    "structured_output": False, "vision": False, "embeddings": False,
                    "reasoning": False, "code_specialization": False, "contract_version": "v1",
                },
                "provider_id": "local", "hosting_mode": "local", "enabled": False,
                "contract_version": "v1",
            }],
        }
    )
    model = response.models[0]
    assert model.hosting_mode is ModelHostingMode.LOCAL
    assert model.enabled is False
    assert model.capabilities.tool_calling is True
