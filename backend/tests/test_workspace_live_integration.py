"""Step 32 — live HTTP integration for the workspace execution path.

End-to-end proof over the real transport (FastAPI ``TestClient`` exercising the
actual routes, ``RunService``, ``NativeAgentAdapter``, ``WorkspaceResolver``,
and the ``AgentRuntimePort.execute`` boundary):

    POST /runs (with workspace_id)
      → RunRequest.workspace_id
      → WorkspaceResolver
      → RuntimeWorkspaceBinding
      → runtime.execute(workspace=...)

The app's *runtime* and *model provider* are swapped for deterministic offline
ports (test/development wiring, matching the repository's existing integration
pattern); the routes, contracts, service, agent, resolver, registry, and
binding are the real production code. The recording runtime echoes the opaque
``workspace_id`` and kind it received (never a path or permissions) so linkage
is observable through the public event stream.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.api.app import create_app
from ava.contracts.models import (
    ModelCapabilities,
    ModelHostingMode,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.execution.selector import ExecutionSelector
from ava.models.bindings import ConfiguredModelBinding, ModelBindingResolver
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes import RuntimeResolver
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.runtimes.registry import RuntimeRegistry
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore
from ava.services.runtime_discovery_service import RuntimeDiscoveryService
from ava.workspaces import (
    ResolvedWorkspace,
    RuntimeWorkspaceBinding,
    WorkspaceInfo,
    WorkspaceKind,
    WorkspacePermissions,
)


class EchoProvider(ModelProviderPort):
    """Port-valid offline provider for deterministic HTTP runs."""

    __test__ = False

    def name(self) -> str:
        return "local"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="local-model",
            provider_name="local",
            display_name="Local",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content=f"echo:{request.messages[0].content}", model_id="local-model")


class RecordingRuntime(AgentRuntimePort):
    """Records the workspace binding each execution receives, then echoes it."""

    def __init__(self, runtime_id: str = "native") -> None:
        self.runtime_id = runtime_id
        self.received: list[RuntimeWorkspaceBinding | None] = []
        self.calls = 0

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(runtime_id=self.runtime_id, display_name=self.runtime_id, capabilities=RuntimeCapabilities())

    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
    ) -> RuntimeRunResult:
        del model_provider, model_binding
        self.calls += 1
        self.received.append(workspace)
        safe = "none"
        if workspace is not None:
            safe = f"{workspace.workspace_id}/{workspace.kind.value}"
        content = f"{run_id}:{self.runtime_id}:{request.prompt}:{safe}"
        return RuntimeRunResult(status=RunStatus.COMPLETED, content=content)

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        del run_id
        return RuntimeRunResult(status=RunStatus.CANCELLED)


def ephemeral_workspace(workspace_id: str) -> ResolvedWorkspace:
    """A safe test workspace: ephemeral kind, no directory, no permissions."""
    return ResolvedWorkspace(
        info=WorkspaceInfo(
            workspace_id=workspace_id,
            display_name=f"Validation {workspace_id}",
            kind=WorkspaceKind.EPHEMERAL,
        ),
        root_path=None,
        permissions=WorkspacePermissions(),
    )


def make_offline_app(workspace_id: str | None = None) -> FastAPI:
    """Compose the real app with deterministic offline runtime/provider ports."""
    app = create_app()
    if workspace_id is not None:
        app.state.workspace_registry.register(ephemeral_workspace(workspace_id))

    runtime_registry: RuntimeRegistry = RuntimeRegistry()
    runtime_registry.register("native", RecordingRuntime(runtime_id="native"))
    runtime_registry.register("openhands", RecordingRuntime(runtime_id="openhands"))
    provider_registry = ModelProviderRegistry()
    provider_registry.register("local", EchoProvider())

    runtime_resolver = RuntimeResolver(runtime_registry)
    provider_resolver = ModelProviderResolver(provider_registry)
    model_binding_resolver = ModelBindingResolver(
        ModelRegistry(
            [
                ModelProfile(
                    model_id="local-model",
                    display_name="Local Model",
                    provider_id="local",
                    provider_model_name="local-model",
                    hosting_mode=ModelHostingMode.LOCAL,
                    capabilities=ModelCapabilities(chat=True),
                )
            ]
        ),
        default_model_id="local-model",
    )

    app.state.runtime_registry = runtime_registry
    app.state.runtime_resolver = runtime_resolver
    app.state.model_provider_registry = provider_registry
    app.state.model_provider_resolver = provider_resolver
    app.state.runtime_discovery_service = RuntimeDiscoveryService(
        registry=runtime_registry, default_runtime_id="native"
    )
    app.state.model_provider_discovery_service = ModelProviderDiscoveryService(
        registry=provider_registry, default_provider_id="local"
    )
    app.state.agent_port = NativeAgentAdapter(
        execution_selector=ExecutionSelector(
            runtime_resolver=runtime_resolver,
            model_provider_resolver=provider_resolver,
            model_binding_resolver=model_binding_resolver,
            default_runtime_id="native",
            default_model_provider_id="local",
            runtime_registry=runtime_registry,
            model_provider_registry=provider_registry,
            eligible_runtime_ids=frozenset({"native"}),
        ),
        workspace_resolver=app.state.workspace_resolver,
    )
    app.state.run_service = RunService(
        app.state.agent_port,
        run_repository=RunStore(),
        run_event_repository=RunEventStore(),
    )
    return app


# ============================================================
# BEGIN: Workspace Discovery Over HTTP
# ============================================================


def test_get_workspaces_empty_registry_over_http() -> None:
    app = make_offline_app()
    with TestClient(app) as client:
        response = client.get("/workspaces")
    assert response.status_code == 200
    assert response.json() == {"contract_version": "v1", "workspaces": []}


def test_get_workspaces_exposes_only_public_identity_over_http() -> None:
    app = make_offline_app()
    app.state.workspace_registry.register(ephemeral_workspace("ephemeral-validation"))
    with TestClient(app) as client:
        response = client.get("/workspaces")
    assert response.status_code == 200
    items = response.json()["workspaces"]
    assert items == [
        {
            "workspace_id": "ephemeral-validation",
            "display_name": "Validation ephemeral-validation",
            "kind": "ephemeral",
        }
    ]


# ============================================================
# BEGIN: Selected Workspace Reaches the Runtime Over HTTP
# ============================================================


def test_selected_workspace_resolves_to_non_none_runtime_binding_over_http() -> None:
    app = make_offline_app("ephemeral-validation")
    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={"prompt": "check the ephemeral workspace", "workspace_id": "ephemeral-validation"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"

    runtime = app.state.runtime_registry.get("native")
    assert runtime is not None and isinstance(runtime, RecordingRuntime)
    assert runtime.calls == 1
    binding = runtime.received[0]
    assert isinstance(binding, RuntimeWorkspaceBinding)
    assert binding.workspace_id == "ephemeral-validation"
    assert binding.kind == WorkspaceKind.EPHEMERAL
    assert binding.local_path is None
    assert binding.permissions == WorkspacePermissions()

    run_id = body["run_id"]
    with TestClient(app) as client:
        events = client.get(f"/runs/{run_id}/events").json()
    contents = [event["payload"]["content"] for event in events if event["event_type"] == "message_content"]
    assert contents == [f"{run_id}:native:check the ephemeral workspace:ephemeral-validation/ephemeral"]
    assert "home" not in "|".join(contents)
    assert not Path(str(contents[0])).is_absolute()


def test_no_workspace_reaches_runtime_as_none_over_http() -> None:
    app = make_offline_app("ephemeral-validation")
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "plain prompt"})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    runtime = app.state.runtime_registry.get("native")
    assert runtime is not None and isinstance(runtime, RecordingRuntime)
    assert runtime.received == [None]

    run_id = response.json()["run_id"]
    with TestClient(app) as client:
        events = client.get(f"/runs/{run_id}/events").json()
    contents = [event["payload"]["content"] for event in events if event["event_type"] == "message_content"]
    assert contents == [f"{run_id}:native:plain prompt:none"]


# ============================================================
# BEGIN: Unknown and Path-Like IDs Fail Closed Over HTTP
# ============================================================


@pytest.mark.parametrize("workspace_id", ["missing-workspace", "/home/bizon/AvaUi", "../project", "/tmp/test"])
def test_unknown_or_path_like_workspace_fails_closed_over_http(workspace_id: str) -> None:
    app = make_offline_app("ephemeral-validation")
    runtime = app.state.runtime_registry.get("native")
    assert isinstance(runtime, RecordingRuntime)

    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "hello", "workspace_id": workspace_id})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert runtime.calls == 0

    with TestClient(app) as client:
        events = client.get(f"/runs/{response.json()['run_id']}/events").json()
    assert any(event["event_type"] == "run_failed" for event in events)
    assert all(event["event_type"] != "message_content" for event in events)


# ============================================================
# BEGIN: Execution Selection and Workspace Are Independent
# ============================================================


def test_explicit_runtime_and_workspace_coexist_independently_over_http() -> None:
    """OpenHands profile + selected workspace both reach the backend."""
    app = make_offline_app("ephemeral-validation")
    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={
                "prompt": "profile prompt",
                "execution": {"runtime_id": "openhands", "model_provider_id": "local"},
                "workspace_id": "ephemeral-validation",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_selection"]["runtime_id"] == "openhands"
    assert body["execution_selection"]["model_provider_id"] == "local"

    openhands = app.state.runtime_registry.get("openhands")
    assert isinstance(openhands, RecordingRuntime)
    assert isinstance(openhands.received[0], RuntimeWorkspaceBinding)
    assert openhands.received[0].workspace_id == "ephemeral-validation"


def test_auto_execution_does_not_grant_workspace_over_http() -> None:
    """Auto routing is unchanged; a carried workspace does not alter it."""
    app = make_offline_app("ephemeral-validation")
    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={"prompt": "auto prompt", "execution": {"mode": "auto"}, "workspace_id": "ephemeral-validation"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_selection"]["runtime_id"] == "native"


# ============================================================
# END
# ============================================================

def test_public_runtime_failure_hides_host_paths_and_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(self: RecordingRuntime, **kwargs: object) -> RuntimeRunResult:
        raise OSError("/tmp/ava-secret-root-123 AVA_FAKE_SECRET_DO_NOT_LEAK")

    monkeypatch.setattr(RecordingRuntime, "execute", fail)
    with TestClient(make_offline_app()) as client:
        response = client.post("/runs", json={"prompt": "offline security test"})
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        events = client.get(f"/runs/{run_id}/events")
        combined = response.text + events.text
        assert "ava-secret-root-123" not in combined
        assert "AVA_FAKE_SECRET_DO_NOT_LEAK" not in combined
        assert "The agent failed to complete the run." in events.text
