"""Backend-authoritative feature evaluation, separate from execution policy."""

from collections.abc import Callable
from typing import Literal

from ava.contracts.tool_features import (
    ToolFeatureAdministrationPort,
    ToolFeatureAvailability,
    ToolFeatureConfiguration,
    ToolFeaturesResponse,
    UpdateToolFeaturesRequest,
)
from ava.contracts.tools import ToolDefinition
from ava.repositories.tool_feature_repository import ToolFeatureConflictError as ToolFeatureConflictError
from ava.repositories.tool_feature_repository import ToolFeatureRepository
from ava.tools import ToolRegistry


class ToolFeatureAdministrationRequiredError(PermissionError):
    pass


class ToolFeatureUnavailableError(ValueError):
    pass


class DenyToolFeatureAdministration:
    def can_manage(self) -> bool:
        return False


class ToolFeatureService:
    def __init__(
        self,
        registry: ToolRegistry,
        repository: ToolFeatureRepository,
        administration: ToolFeatureAdministrationPort | None = None,
        *,
        on_configuration_changed: Callable[[], object] | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._administration = administration or DenyToolFeatureAdministration()
        self._on_configuration_changed = on_configuration_changed

    def _can_manage(self) -> bool:
        try:
            return self._administration.can_manage() is True
        except Exception:
            return False

    def state(self) -> ToolFeaturesResponse:
        definitions = self._registry.list()
        known = {definition.tool_id for definition in definitions}
        status: Literal["missing", "valid", "invalid"] = "valid"
        try:
            saved = self._repository.get()
            if saved is None:
                status = "missing"
                configuration = ToolFeatureConfiguration()
            else:
                configuration = ToolFeatureConfiguration.model_validate(saved.model_dump(warnings=False))
                if not set(configuration.enabled_tool_ids).issubset(known):
                    raise ValueError("configuration references unknown tools")
        except Exception:
            status = "invalid"
            configuration = ToolFeatureConfiguration()
        tools = []
        for definition in definitions:
            configured = definition.tool_id in configuration.enabled_tool_ids
            reason: Literal["configuration_invalid", "framework_disabled", "tool_disabled", "feature_enabled"] = (
                "configuration_invalid"
                if status == "invalid"
                else (
                    "framework_disabled"
                    if not configuration.framework_enabled
                    else ("tool_disabled" if not configured else "feature_enabled")
                )
            )
            tools.append(
                ToolFeatureAvailability(
                    definition=definition,
                    configured_enabled=configured,
                    effective_enabled=reason == "feature_enabled",
                    reason=reason,
                )
            )
        return ToolFeaturesResponse(
            configuration=configuration,
            configuration_status=status,
            framework_effective_enabled=status != "invalid" and configuration.framework_enabled,
            can_manage=self._can_manage() and status != "invalid",
            tools=tools,
        )

    def update(self, request: UpdateToolFeaturesRequest) -> ToolFeaturesResponse:
        if not self._can_manage():
            raise ToolFeatureAdministrationRequiredError("Authenticated feature administration is unavailable.")
        try:
            request = UpdateToolFeaturesRequest.model_validate(request.model_dump())
        except ValueError as exc:
            raise ValueError("Invalid feature configuration request.") from exc
        state = self.state()
        if state.configuration_status == "invalid":
            raise ValueError("Feature configuration is invalid; administrator repair is required.")
        ids = request.enabled_tool_ids
        if len(ids) != len(set(ids)) or any(self._registry.get(tool_id) is None for tool_id in ids):
            raise ValueError("Enabled tool IDs must be unique registered tools.")
        configuration = ToolFeatureConfiguration(
            framework_enabled=request.framework_enabled,
            enabled_tool_ids=tuple(sorted(ids)),
            configuration_version=request.expected_version + 1,
        )
        if not self._can_manage():
            raise ToolFeatureAdministrationRequiredError("Feature administration authority was withdrawn.")
        self._repository.compare_and_set(request.expected_version, configuration)
        if self._on_configuration_changed is not None:
            self._on_configuration_changed()
        return self.state()

    def require_enabled(self, tool_id: str) -> ToolDefinition:
        """Fresh gate check for future dispatch; not Workspace/policy/approval authorization."""
        for item in self.state().tools:
            if item.definition.tool_id == tool_id:
                if not item.effective_enabled:
                    raise ToolFeatureUnavailableError(item.reason)
                return item.definition
        raise ToolFeatureUnavailableError("unknown_tool")
