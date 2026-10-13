"""In-process catalog of trusted, validated AVA tool definitions.

Only application composition should register definitions. This catalog has no
handlers, enablement, policy, Workspace resolution or plugin-loading behavior.
"""

from __future__ import annotations

import builtins
from collections.abc import Collection
from threading import Lock

from ava.contracts.tools import ToolCapability, ToolDefinition, ToolExecutionCategory


class ToolRegistry:
    """Own isolated definition snapshots, returning defensive copies on reads."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._lock = Lock()

    def register(self, definition: ToolDefinition) -> None:
        """Revalidate and snapshot one definition; reject every duplicate ID.

        Pydantic frozen models contain mutable nested schemas and
        model_construct/model_copy can bypass validation. Dumping into the
        existing contract validates those values again and takes ownership of
        new containers. Registration never advertises an executable handler.
        """
        if not isinstance(definition, ToolDefinition):
            raise TypeError("registration requires an AVA ToolDefinition")
        snapshot = ToolDefinition.model_validate(definition.model_dump(warnings=False))
        with self._lock:
            if snapshot.tool_id in self._definitions:
                raise ValueError(f"Tool already registered: {snapshot.tool_id}")
            self._definitions[snapshot.tool_id] = snapshot

    def get(self, tool_id: str) -> ToolDefinition | None:
        """Return a detached definition, or None for an unknown identity."""
        with self._lock:
            definition = self._definitions.get(tool_id)
            return definition.model_copy(deep=True) if definition is not None else None

    def list(self) -> builtins.list[ToolDefinition]:
        """Return detached snapshots sorted lexically by stable tool ID."""
        return self.discover()

    def discover(
        self,
        *,
        capabilities: Collection[ToolCapability] = (),
        category: ToolExecutionCategory | None = None,
    ) -> builtins.list[ToolDefinition]:
        """Filter declarations, not effective permissions or availability.

        A definition must declare all queried capabilities and match the
        category when supplied. Empty capabilities mean no capability filter;
        category and capability filters intersect. Ordering matches list().
        """
        required = frozenset(capabilities)
        if any(not isinstance(value, ToolCapability) for value in required):
            raise ValueError("capability filters must be AVA ToolCapability values")
        if category is not None and not isinstance(category, ToolExecutionCategory):
            raise ValueError("category filter must be an AVA ToolExecutionCategory")
        with self._lock:
            return [
                definition.model_copy(deep=True)
                for _, definition in sorted(self._definitions.items())
                if required.issubset(definition.required_capabilities)
                and (category is None or definition.execution_category == category)
            ]
