"""Mock agent adapter.

First concrete implementation of the AVA-owned ``AgentPort``. It exists to
validate AVA's execution flow without binding AVA to an AI framework or
provider; it performs no real inference and has no provider dependency.
"""

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter

__all__ = ["MockAgentAdapter"]