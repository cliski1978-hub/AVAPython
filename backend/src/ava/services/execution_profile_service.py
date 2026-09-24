from ava.contracts.responses import ExecutionProfile, ExecutionProfileDiscoveryResponse


class ExecutionProfileService:
    def __init__(self, *, runtime_id: str, provider_id: str) -> None:
        self._runtime_id, self._provider_id = runtime_id, provider_id

    def discover(self) -> ExecutionProfileDiscoveryResponse:
        return ExecutionProfileDiscoveryResponse(
            default_profile_id="local-default",
            profiles=[
                ExecutionProfile(
                    id="local-default",
                    name="Local Coding",
                    description="AVA local coding execution",
                    runtime_id=self._runtime_id,
                    model_provider_id=self._provider_id,
                ),
                ExecutionProfile(
                    id="openhands-local",
                    name="OpenHands Local",
                    description="OpenHands with approved workspace file access",
                    runtime_id="openhands",
                    model_provider_id=self._provider_id,
                ),
            ],
        )
