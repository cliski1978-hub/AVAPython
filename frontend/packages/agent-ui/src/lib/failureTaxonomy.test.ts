/**
 * The conversation failure presentation map, asserted code by code.
 *
 * This is the user-visible half of the failure taxonomy. Each supported code
 * must resolve to a specific title, a safe description, and a correct Settings
 * target; and an unsupported or missing code must degrade to the generic
 * presentation rather than rendering an empty or partially-mapped failure.
 *
 * The map is also asserted against the backend's code list, so a code added on
 * the backend without a presentation here fails this suite instead of silently
 * losing its guidance in the UI.
 */

import { describe, expect, it } from "vitest";

import {
  describeRunFailure,
  isFailureRetryable,
  presentRunFailure,
  settingsSectionForFailure,
} from "./errorPresentation";

/** The backend's stable codes (`ava.contracts.failures.FailureCode`). */
const BACKEND_FAILURE_CODES = [
  "configuration_missing",
  "configuration_invalid",
  "provider_connection_unavailable",
  "model_unavailable",
  "runtime_unavailable",
  "credential_unavailable",
  "provider_request_failed",
  "provider_timeout",
  "provider_rate_limited",
  "provider_authentication_failed",
  "provider_response_invalid",
  "runtime_failed",
  "context_window_exceeded",
  "cancelled",
  "execution_interrupted",
  "agent_failed",
] as const;

describe("every backend failure code has a presentation", () => {
  it.each(BACKEND_FAILURE_CODES)("%s resolves to specific wording", (code) => {
    const presentation = describeRunFailure(code);
    expect(presentation.title.length).toBeGreaterThan(0);
    expect(presentation.description.length).toBeGreaterThan(0);
  });

  it("no code is left on the generic presentation", () => {
    const generic = describeRunFailure("agent_failed");
    // agent_failed is the generic presentation by definition; every other code
    // must have its own.
    const unmapped = BACKEND_FAILURE_CODES.filter((code) => code !== "agent_failed").filter((code) => {
      const presentation = describeRunFailure(code);
      return presentation.title === generic.title && presentation.description === generic.description;
    });
    expect(unmapped).toEqual([]);
  });

  it("each description names the problem and stays free of provider internals", () => {
    for (const code of BACKEND_FAILURE_CODES) {
      const { description } = describeRunFailure(code);
      expect(description).not.toMatch(/http/i);
      expect(description).not.toMatch(/api[_ ]?key/i);
      expect(description).not.toMatch(/bearer|authorization/i);
      expect(description).not.toMatch(/\d{3} status/i);
    }
  });
});

describe("model and provider failures are distinguished", () => {
  it("names an unusable model as a model problem", () => {
    const presentation = describeRunFailure("model_unavailable");
    expect(presentation.title).toBe("Model unavailable");
    expect(presentation.description).toBe(
      "The configured model could not be found or used by the selected provider. Check the model configuration or choose another model.",
    );
    expect(presentation.settingsSection).toBe("models");
    expect(presentation.retryable).toBe(true);
  });

  it("names an unreachable provider as a connectivity problem, not a model problem", () => {
    const presentation = describeRunFailure("provider_connection_unavailable");
    expect(presentation.title).toBe("Provider unavailable");
    expect(presentation.description).toBe(
      "AVA could not reach the configured model provider. Check the provider endpoint or provider availability.",
    );
    expect(presentation.settingsSection).toBe("providers");
    // The two must not read alike, or the user cannot tell which to fix.
    expect(presentation.description).not.toBe(describeRunFailure("model_unavailable").description);
  });

  it("gives timeout, rate limit, authentication, and invalid response distinct wording", () => {
    const titles = [
      "provider_timeout",
      "provider_rate_limited",
      "provider_authentication_failed",
      "provider_response_invalid",
    ].map((code) => describeRunFailure(code).title);
    expect(new Set(titles).size).toBe(titles.length);
    expect(describeRunFailure("provider_timeout").title).toBe("Model request timed out");
    expect(describeRunFailure("provider_rate_limited").title).toBe("Provider rate limit reached");
    expect(describeRunFailure("provider_authentication_failed").title).toBe("Provider authentication failed");
    expect(describeRunFailure("provider_response_invalid").title).toBe("Invalid provider response");
  });

  it("targets Settings for the failures a user can fix there", () => {
    expect(settingsSectionForFailure("provider_timeout")).toBe("providers");
    expect(settingsSectionForFailure("provider_authentication_failed")).toBe("providers");
    expect(settingsSectionForFailure("credential_unavailable")).toBe("providers");
    expect(settingsSectionForFailure("runtime_unavailable")).toBe("runtimes");
    expect(settingsSectionForFailure("configuration_missing")).toBe("defaults");
    expect(settingsSectionForFailure("configuration_invalid")).toBe("defaults");
  });

  it("offers no Settings target for provider faults with no configuration to change", () => {
    expect(settingsSectionForFailure("provider_rate_limited")).toBeUndefined();
    expect(settingsSectionForFailure("provider_response_invalid")).toBeUndefined();
    expect(settingsSectionForFailure("agent_failed")).toBeUndefined();
    expect(settingsSectionForFailure("execution_interrupted")).toBeUndefined();
  });

  it("explains a context-window failure as a conversation-size problem", () => {
    const presentation = describeRunFailure("context_window_exceeded");
    expect(presentation.title).toBe("Conversation too large for this model");
    expect(presentation.description).toMatch(/larger context window/);
    // Retrying the identical conversation cannot help.
    expect(presentation.retryable).toBe(false);
  });

  it("offers retry only where retrying can plausibly help", () => {
    expect(isFailureRetryable("provider_timeout")).toBe(true);
    expect(isFailureRetryable("provider_rate_limited")).toBe(true);
    expect(isFailureRetryable("model_unavailable")).toBe(true);
    expect(isFailureRetryable("context_window_exceeded")).toBe(false);
    expect(isFailureRetryable("configuration_invalid")).toBe(false);
    expect(isFailureRetryable("provider_authentication_failed")).toBe(false);
    expect(isFailureRetryable("agent_failed")).toBe(true);
  });
});

describe("the generic fallback is preserved", () => {
  it("keeps the established wording for agent_failed", () => {
    expect(describeRunFailure("agent_failed").title).toBe("Failed to generate response");
    expect(describeRunFailure("agent_failed").description).toBe(
      "Something prevented this response from completing.",
    );
  });

  it.each([
    ["an unknown code", "some_future_failure"],
    ["an empty code", ""],
  ])("degrades %s to the generic presentation", (_label, code) => {
    expect(describeRunFailure(code)).toEqual(describeRunFailure("agent_failed"));
    expect(presentRunFailure({ error_code: code })).toBe("Something prevented this response from completing.");
  });

  it("degrades a payload with no code at all", () => {
    expect(describeRunFailure(undefined)).toEqual(describeRunFailure("agent_failed"));
    expect(describeRunFailure(null)).toEqual(describeRunFailure("agent_failed"));
    expect(presentRunFailure({})).toBe("Something prevented this response from completing.");
  });

  it("ignores a non-string error_code rather than rendering it", () => {
    expect(presentRunFailure({ error_code: 42 })).toBe("Something prevented this response from completing.");
  });
});
