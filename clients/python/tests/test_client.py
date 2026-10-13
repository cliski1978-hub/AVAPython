"""AvaClient HTTP-level tests using an in-memory mock transport."""

from collections.abc import Callable

import httpx

from ava_client import AvaClient
from ava_client.models import WorkspaceDiscoveryResponse, WorkspaceKind

Handler = Callable[[httpx.Request], httpx.Response]


def _mock_transport(handler: Handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_get_workspaces_requests_path_and_deserializes() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "contract_version": "v1",
                "workspaces": [
                    {"workspace_id": "temporary-test", "display_name": "Temporary Test", "kind": "local"},
                    {"workspace_id": "project-test", "display_name": "Project Test", "kind": "local"},
                ],
            },
        )

    with AvaClient(
        "http://backend.test", transport=_mock_transport(handler)
    ) as client:
        response = client.get_workspaces()

    assert requested_paths == ["/workspaces"]
    assert isinstance(response, WorkspaceDiscoveryResponse)
    assert response.contract_version == "v1"
    assert [item.workspace_id for item in response.workspaces] == [
        "temporary-test",
        "project-test",
    ]
    assert response.workspaces[1].kind is WorkspaceKind.LOCAL


def test_get_workspaces_empty_registry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"contract_version": "v1", "workspaces": []})

    with AvaClient("http://backend.test", transport=_mock_transport(handler)) as client:
        response = client.get_workspaces()

    assert response.workspaces == []


def test_get_workspaces_never_contains_internal_fields() -> None:
    """A backend response cannot smuggle path fields into client models."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "contract_version": "v1",
                "workspaces": [
                    {"workspace_id": "project-test", "display_name": "Project Test", "kind": "local"}
                ],
            },
        )

    with AvaClient("http://backend.test", transport=httpx.MockTransport(handler)) as client:
        response = client.get_workspaces()

    payload = response.model_dump()
    assert set(payload) == {"contract_version", "workspaces"}
    assert set(payload["workspaces"][0]) == {"workspace_id", "display_name", "kind"}
    for key in ("root_path", "local_path", "permissions"):
        assert key not in str(payload), key


def test_list_models_requests_safe_catalog_and_deserializes() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(200, json={
            "contract_version": "v1",
            "default_model_id": "ava/local",
            "models": [{
                "provider_name": "local", "model_id": "ava/local", "display_name": "Local",
                "context_limit": None,
                "capabilities": {
                    "chat": True, "streaming": False, "tool_calling": True,
                    "structured_output": False, "vision": False, "embeddings": False,
                    "reasoning": False, "code_specialization": False, "contract_version": "v1",
                },
                "provider_id": "local", "hosting_mode": "local", "enabled": True,
                "contract_version": "v1",
            }],
        })

    with AvaClient("http://backend.test", transport=_mock_transport(handler)) as client:
        response = client.list_models()

    assert requested_paths == ["/models"]
    assert response.models[0].model_id == "ava/local"
    assert response.models[0].hosting_mode is not None
    assert response.default_model_id == "ava/local"
    assert "provider_model_name" not in str(response.model_dump())
