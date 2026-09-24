"""Pure container for caller-constructed AVA runtime instances."""

from ava.runtimes.contracts import AgentRuntimePort


class RuntimeRegistry:
    """Store runtime references by opaque id, without construction or lifecycle.

    Registration does not inspect runtime metadata or choose a model. Selection
    and resolution policy belong to callers and future resolver work.
    """

    def __init__(self) -> None:
        self._runtimes: dict[str, AgentRuntimePort] = {}

    def register(self, runtime_id: str, runtime: AgentRuntimePort) -> None:
        """Store an existing instance; reject blank or duplicate ids.

        Nonblank ids are preserved exactly, without trimming or alias handling.
        The registry key need not match the runtime's metadata identity.
        """
        if not runtime_id or not runtime_id.strip():
            raise ValueError("Runtime id must be a non-blank string")
        if runtime_id in self._runtimes:
            raise ValueError(f"Runtime already registered: {runtime_id!r}")
        self._runtimes[runtime_id] = runtime

    def get(self, runtime_id: str) -> AgentRuntimePort | None:
        """Return the stored instance, or None for an unknown id."""
        return self._runtimes.get(runtime_id)

    def contains(self, runtime_id: str) -> bool:
        """Return whether this exact id is registered."""
        return runtime_id in self._runtimes

    def list(self) -> list[str]:
        """Return a fresh list of registered ids in insertion order."""
        return list(self._runtimes)
