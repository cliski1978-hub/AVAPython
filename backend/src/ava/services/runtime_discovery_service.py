from ava.contracts.responses import RuntimeDiscoveryItem, RuntimeDiscoveryResponse
from ava.runtimes.registry import RuntimeRegistry


class RuntimeDiscoveryService:
    def __init__(self, *, registry: RuntimeRegistry, default_runtime_id: str) -> None:
        self._registry = registry
        self._default_runtime_id = default_runtime_id

    def discover(self) -> RuntimeDiscoveryResponse:
        runtimes = []
        for runtime_id in self._registry.list():
            runtime = self._registry.get(runtime_id)
            if runtime is None:
                continue
            info = runtime.get_runtime_info()
            runtimes.append(
                RuntimeDiscoveryItem(is_default=info.runtime_id == self._default_runtime_id, runtime_info=info)
            )
        return RuntimeDiscoveryResponse(default_runtime_id=self._default_runtime_id, runtimes=runtimes)
