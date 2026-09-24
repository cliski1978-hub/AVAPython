"""Controlled conversation for the pinned OpenHands SDK 1.47.0.

The SDK otherwise discovers ambient user/project plugins and their executable
hooks on send_message/run. AVA grants only the tools it explicitly constructs.
Keep this private SDK override covered when updating the optional dependency.
"""

import inspect
from pathlib import Path
from typing import Any

from openhands.sdk import Agent, LocalConversation
from openhands.sdk.conversation.state import ConversationState
from openhands.sdk.tool import ToolDefinition
from openhands.sdk.tool.registry import resolve_tool


class ControlledAgent(Agent):
    @property
    def prompt_dir(self) -> str:
        """Retain the SDK's built-in prompts when subclassing its agent."""
        return str(Path(inspect.getfile(Agent)).parent / "prompts")

    def _initialize(self, state: ConversationState) -> None:
        """Resolve only AVA's explicit controlled tools; SDK builtins are not grants."""
        if self._initialized:
            return
        tools: list[ToolDefinition[Any, Any]] = []
        for spec in self.tools:
            if spec.name not in {"file_editor", "ava_terminal"}:
                raise ValueError("Only AVA-controlled tools are allowed")
            tools.extend(resolve_tool(spec, state))
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)) or any(name not in {"file_editor", "ava_terminal"} for name in names):
            raise ValueError("Unexpected OpenHands tools")
        self._tools = {tool.name: tool for tool in tools}
        self._initialized = True


class ControlledConversation(LocalConversation):
    def _register_file_based_agents(self) -> None:
        """Workspace files cannot register executable agents."""

    def _ensure_plugins_loaded(self) -> None:
        """Disable ambient plugins, skills, MCP servers, memory, and hooks."""
        self._plugins_loaded = True
