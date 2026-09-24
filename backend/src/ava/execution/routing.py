from dataclasses import dataclass

from ava.contracts.requests import RunRequest
from ava.execution.compatibility import ExecutionCompatibilityValidator
from ava.models.registry import ModelProviderRegistry
from ava.runtimes.registry import RuntimeRegistry


@dataclass(frozen=True)
class ExecutionRouteDecision:
    runtime_id: str
    model_provider_id: str
    reason: str

class AutomaticExecutionRoutingPolicy:
    def __init__(self, *, runtime_registry: RuntimeRegistry, model_provider_registry: ModelProviderRegistry, validator: ExecutionCompatibilityValidator | None = None, eligible_runtime_ids: frozenset[str] | None = None) -> None:
        self.runtimes = runtime_registry; self.providers = model_provider_registry; self.validator = validator or ExecutionCompatibilityValidator(); self.eligible_runtime_ids = eligible_runtime_ids

    def select(self, *, request: RunRequest, default_runtime_id: str, default_model_provider_id: str) -> ExecutionRouteDecision:
        pairs = [(default_runtime_id, default_model_provider_id)] + [(r, p) for r in self.runtimes.list() for p in self.providers.list() if (r, p) != (default_runtime_id, default_model_provider_id) and r != "openhands"]
        for rid, pid in pairs:
            if self.eligible_runtime_ids is not None and rid not in self.eligible_runtime_ids:
                continue
            runtime, provider = self.runtimes.get(rid), self.providers.get(pid)
            if runtime and provider and self.validator.validate(request=request, runtime=runtime, model_provider=provider).compatible:
                reason = "Configured default compatible execution" if (rid, pid) == (default_runtime_id, default_model_provider_id) else "First compatible registered execution"
                return ExecutionRouteDecision(rid, pid, reason)
        raise ValueError("No compatible execution configuration is available")
 # ruff: noqa: E501, E702
