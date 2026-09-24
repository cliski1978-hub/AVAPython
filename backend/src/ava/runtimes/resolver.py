"""Exact runtime-id resolution over an injected registry, without defaults."""

from ava.runtimes.contracts import AgentRuntimePort
from ava.runtimes.registry import RuntimeRegistry


class UnknownRuntimeError(ValueError):
    """An unresolved runtime id; carries no registry or implementation details."""

    def __init__(self, runtime_id: str) -> None:
        self.runtime_id = runtime_id
        super().__init__(f"Unknown runtime: {runtime_id!r}")


class RuntimeResolver:
    """Resolve existing runtime references without construction or execution.

    Runtime and model-provider resolution are independent. Configuration,
    defaults, metadata inspection, and provider selection do not belong here.
    """

    def __init__(self, registry: RuntimeRegistry) -> None:
        self._registry = registry

    def resolve(self, runtime_id: str) -> AgentRuntimePort:
        """Return the exact registered instance; reject blank or unknown ids.

        Raises:
            UnknownRuntimeError: If the original id is blank or unregistered.
                Nonblank ids are looked up unchanged, without normalization.
        """
        if not runtime_id or not runtime_id.strip():
            raise UnknownRuntimeError(runtime_id)
        runtime = self._registry.get(runtime_id)
        if runtime is None:
            raise UnknownRuntimeError(runtime_id)
        return runtime
