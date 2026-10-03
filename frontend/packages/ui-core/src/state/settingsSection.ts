/** Neutral Settings destination shared by UI producers and application hosts. */
export type SettingsSectionId = "providers" | "models" | "runtimes" | "defaults" | "system-prompts";

/**
 * Human label for a Settings section.
 *
 * A failure action must name where it is taking the user — "Open Model
 * Settings" tells them what to fix, where a bare "Open Settings" leaves them
 * hunting. Lives beside the id so a new section cannot forget its label.
 */
export const settingsSectionLabel: Record<SettingsSectionId, string> = {
  providers: "Provider",
  models: "Model",
  runtimes: "Runtime",
  defaults: "Default",
  "system-prompts": "System Prompts",
};
