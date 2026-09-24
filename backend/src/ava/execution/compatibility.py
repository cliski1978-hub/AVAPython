from dataclasses import dataclass

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.contracts.requests import RunRequest
from ava.execution.hosting import HostingReason, ModelHostingRequirement
from ava.models.contracts import ModelProviderPort
from ava.runtimes.contracts import AgentRuntimePort


@dataclass(frozen=True)
class ExecutionCompatibilityResult:
    compatible: bool
    reasons: tuple[str, ...] = ()


class ExecutionCompatibilityValidator:
    """Runtime-neutral compatibility checks applied before execution.

    Placement (hosting) policy is evaluated here — not inside providers and not
    inside runtimes — so a disallowed deployment is rejected before any provider
    request is made. When no ``hosting_requirement`` is supplied, hosting is
    unconstrained and every configured mode remains potentially compatible.

    Declared model capabilities may be supplied directly (from the resolved
    ``ModelProfile``) so the check uses the registry's catalog metadata rather
    than asking a provider ad hoc. When omitted, the provider's reported
    capabilities are used instead.
    """

    def validate(
        self,
        *,
        request: RunRequest,
        runtime: AgentRuntimePort,
        model_provider: ModelProviderPort,
        hosting_mode: ModelHostingMode | None = None,
        hosting_requirement: ModelHostingRequirement | None = None,
        model_capabilities: ModelCapabilities | None = None,
    ) -> ExecutionCompatibilityResult:
        del request
        try:
            runtime.get_runtime_info()
            info = model_provider.get_model_info()
        except Exception:
            return ExecutionCompatibilityResult(False, ("execution metadata unavailable",))
        capabilities = model_capabilities if model_capabilities is not None else info.capabilities
        if not capabilities.chat:
            return ExecutionCompatibilityResult(False, ("selected model does not support chat",))
        if hosting_requirement is not None:
            if hosting_mode is None:
                return ExecutionCompatibilityResult(
                    False, (HostingReason.CLASSIFICATION_UNAVAILABLE.value,)
                )
            if not hosting_requirement.permits(hosting_mode):
                return ExecutionCompatibilityResult(
                    False, (HostingReason.MODE_NOT_ALLOWED.value,)
                )
        return ExecutionCompatibilityResult(True)
