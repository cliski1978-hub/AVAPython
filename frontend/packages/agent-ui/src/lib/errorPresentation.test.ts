/**
 * AVA-owned wording and remediation targeting for known failure codes.
 *
 * The distinction this file protects is the one between a failure AVA can fix
 * through Settings and a failure it cannot. A restart interruption is the
 * canonical example of the second kind: the user cannot repair it by editing a
 * provider connection, so offering an "Open Settings" action would send them
 * somewhere useless and imply a mistake they did not make. The mapping is
 * asserted in both directions — untargeted for non-configuration codes, and
 * still targeted for real configuration codes — so an empty result can never
 * pass by making the whole function return nothing.
 */

import { describe, expect, it } from "vitest";

import { presentRunFailure, settingsSectionForFailure } from "./errorPresentation";

describe("restart interruption is explained but not sent to Settings", () => {
  it("names the restart as the reason in AVA-owned wording", () => {
    expect(presentRunFailure({ error_code: "execution_interrupted" })).toBe(
      "The backend restarted before this response finished. You can retry the request.",
    );
  });

  it("offers no Settings remediation", () => {
    expect(settingsSectionForFailure("execution_interrupted")).toBeUndefined();
  });

  it("still targets Settings for failures a user can actually fix", () => {
    expect(settingsSectionForFailure("configuration_missing")).toBe("defaults");
    expect(settingsSectionForFailure("provider_connection_unavailable")).toBe("providers");
    expect(settingsSectionForFailure("credential_unavailable")).toBe("providers");
    expect(settingsSectionForFailure("model_unavailable")).toBe("models");
    expect(settingsSectionForFailure("runtime_unavailable")).toBe("runtimes");
  });

  it("offers no Settings remediation for the other non-configuration codes", () => {
    expect(settingsSectionForFailure("agent_failed")).toBeUndefined();
    expect(settingsSectionForFailure("conversation_run_active")).toBeUndefined();
    expect(settingsSectionForFailure("run_not_found")).toBeUndefined();
    expect(settingsSectionForFailure(undefined)).toBeUndefined();
  });
});
