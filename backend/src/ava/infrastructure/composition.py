"""Backend composition helpers.

Part of the composition/adaptation layer: selects concrete AVA adapters from
configuration-driven provider names (e.g. ``agent_provider = mock``). This
module may depend on adapter implementations and AVA-owned ports/contracts,
but never the reverse.

Core and services never import adapters directly; they program against the
ports. This module exists so provider choice stays a configuration decision,
as specified by Sprint 1.
"""

import logging
from collections.abc import Callable

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.contracts import AgentPort

logger = logging.getLogger(__name__)

#: Map of configured agent provider names to adapter constructors.
_AGENT_ADAPTER_FACTORIES: dict[str, Callable[[], AgentPort]] = {
    "mock": MockAgentAdapter,
}


def create_agent_adapter(provider: str) -> AgentPort:
    """Construct the agent adapter for the configured provider name.

    Args:
        provider: The ``agent_provider`` value from configuration
            (e.g. ``"mock"``).

    Returns:
        A concrete ``AgentPort`` implementation for the provider.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    factory = _AGENT_ADAPTER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"Unknown agent provider: {provider!r}")
    logger.debug("Selecting agent adapter for provider %r", provider)
    return factory()