/**
 * AVA Settings surface.
 *
 * Configuration management lives here, not in the conversation UI. Web and
 * Desktop both compose this package through `@ava/workspace`; neither shell
 * implements Settings.
 *
 * Phase 5.11 is the foundation: navigation, section structure, shared
 * loading/error/empty patterns, the inventory pattern, and the modal pattern
 * for the management phases. Phase 5.12 added provider-connection management
 * and Phase 5.13 added model management on top of it. Runtimes and execution
 * defaults remain read-only until their own phases, and the architecture guard
 * keeps enforcing that.
 *
 * Security note: the only credential concept in this package is
 * `credential_reference`, an opaque location such as `env:OPENAI_API_KEY`.
 * Resolved secret material is never part of any contract, state, or view here,
 * and the browser is not permitted to hold one.
 */

export {
  SettingsWorkspace,
  type SettingsWorkspaceProps,
} from "./settings/SettingsWorkspace";
export {
  SettingsSectionNav,
  SETTINGS_SECTIONS,
  DEFAULT_SETTINGS_SECTION,
  settingsSectionPanelId,
  type SettingsSectionNavProps,
  type SettingsSectionId,
  type SettingsSectionDefinition,
} from "./settings/SettingsSectionNav";
export {
  SettingsLoading,
  SettingsError,
  SettingsEmpty,
  type SettingsLoadingProps,
  type SettingsErrorProps,
  type SettingsEmptyProps,
} from "./settings/SettingsSectionState";
export {
  SettingsInventory,
  type SettingsInventoryProps,
  type SettingsInventoryEntry,
} from "./inventory/SettingsInventory";
export {
  SettingsModal,
  type SettingsModalProps,
  type SettingsModalState,
} from "./modal/SettingsModal";
export {
  useSettingsResource,
  type SettingsResource,
  type SettingsResourceState,
  type UseSettingsResourceOptions,
} from "./state/useSettingsResource";
export { settingsErrorMessage } from "./state/settingsErrorMessage";
export {
  useSettingsForm,
  type SettingsForm,
  type SettingsFormErrors,
  type SettingsFormOptions,
} from "./state/useSettingsForm";
export { ProviderConnectionsSection } from "./sections/ProviderConnectionsSection";
export { ModelConfigurationsSection } from "./sections/ModelConfigurationsSection";
export { RuntimeConfigurationsSection } from "./sections/RuntimeConfigurationsSection";
export { ExecutionDefaultsSection } from "./sections/ExecutionDefaultsSection";
export { SystemPromptsSection } from "./sections/SystemPromptsSection";
export { CorePromptScopeAssignments, type CorePromptScopeAssignmentsProps, type AssignablePromptScope } from "./prompts/CorePromptScopeAssignments";
export {
  ProviderConnectionEditor,
  type ProviderConnectionEditorProps,
} from "./providers/ProviderConnectionEditor";
export {
  ModelConfigurationEditor,
  type ModelConfigurationEditorProps,
  type ProviderConnectionSummary,
} from "./models/ModelConfigurationEditor";
export {
  CAPABILITY_FIELDS,
  capabilitiesFrom,
  capabilitySummary,
  capabilityToggles,
  emptyCapabilities,
  type CapabilityToggles,
} from "./models/modelCapabilities";
export {
  RuntimeConfigurationEditor,
  type RuntimeConfigurationEditorProps,
} from "./runtimes/RuntimeConfigurationEditor";
export { useRuntimeTypeChoices } from "./runtimes/useRuntimeTypeChoices";
export {
  ExecutionDefaultsEditor,
  type ExecutionDefaultsEditorProps,
} from "./defaults/ExecutionDefaultsEditor";
export {
  modelOptions,
  providerOptions,
  runtimeOptions,
  toChoiceSet,
  displayLabel,
  missingRecordLabel,
  type ChoiceSet,
  type ChoiceStatus,
} from "./defaults/defaultChoices";
