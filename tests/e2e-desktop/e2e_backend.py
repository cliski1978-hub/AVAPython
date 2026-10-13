"""Test-only backend factory that gives mock runs inspectable snapshots."""

from importlib import import_module

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.contracts import AgentRunResult
from ava.contracts.conversations import RunContext, execution_context_messages
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.run_inspection import RunInspectionSnapshot

app_module = import_module("ava.api.app")


class E2EMockAgentAdapter(MockAgentAdapter):
    """Keep deterministic mock responses while capturing E2E Inspector facts."""

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: RunContext | None = None
    ) -> AgentRunResult:
        result = await super().start_run(run_id, request, context=context)
        if result.status is not RunStatus.COMPLETED or context is None:
            return result

        snapshot = RunInspectionSnapshot(
            prompt_layers=context.prompt_layers,
            normalized_request=execution_context_messages(context, request.prompt),
            attachments=context.attachments,
            runtime_request={"prompt": request.prompt},
            runtime_response={"content": result.content},
            normalized_response={"content": result.content},
        )
        return result.model_copy(update={"inspection_snapshot": snapshot})


_create_agent_adapter = app_module.create_agent_adapter


def _create_e2e_agent_adapter(provider: str, **kwargs):
    if provider == "mock":
        return E2EMockAgentAdapter()
    return _create_agent_adapter(provider, **kwargs)


# Patch only the application-factory module imported by this test-only ASGI
# entry point. Normal ``ava.api.app:create_app`` startup remains unchanged.
app_module.create_agent_adapter = _create_e2e_agent_adapter


def create_app():
    return app_module.create_app()
