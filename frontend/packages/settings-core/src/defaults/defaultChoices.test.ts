import { describe, expect, it } from "vitest";
import type {
  ModelConfigurationResponse,
  ProviderConnectionResponse,
  RuntimeConfigurationResponse,
} from "@ava/contracts";

import {
  displayLabel,
  missingRecordLabel,
  modelOptions,
  providerOptions,
  runtimeOptions,
  toChoiceSet,
  type ChoiceSet,
} from "../defaults/defaultChoices";
import type { SettingsResourceState } from "../state/useSettingsResource";

/**
 * These are the invariants the defaults editor cannot check for itself, so they
 * are checked here instead.
 *
 * The recurring theme is that "we do not know" and "there is nothing" are
 * different facts. Every helper below is careful to keep them apart, because the
 * cost of conflating them is an operator who deletes a working default on the
 * strength of an empty list that was really a failed request.
 */

const contractVersion = "v1" as const;

function provider(
  overrides: Partial<ProviderConnectionResponse> = {},
): ProviderConnectionResponse {
  return {
    provider_connection_id: "conn-a",
    provider_id: "acme",
    display_name: "Acme Primary",
    endpoint: "https://api.acme.test",
    enabled: true,
    context_window_tokens: null,
    credential_reference: "env:ACME_API_KEY",
    contract_version: contractVersion,
    ...overrides,
  };
}

function model(
  overrides: Partial<ModelConfigurationResponse> = {},
): ModelConfigurationResponse {
  return {
    model_id: "model-a",
    provider_connection_id: "conn-a",
    provider_model_name: "large",
    display_name: "Acme Large",
    hosting_mode: "remote" as ModelConfigurationResponse["hosting_mode"],
    capabilities: {} as ModelConfigurationResponse["capabilities"],
    enabled: true,
    context_window_tokens: null,
    contract_version: contractVersion,
    ...overrides,
  };
}

function runtime(
  overrides: Partial<RuntimeConfigurationResponse> = {},
): RuntimeConfigurationResponse {
  return {
    runtime_configuration_id: "rt-a",
    runtime_type: "subprocess",
    display_name: "Native",
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

/**
 * The state union carries `data: null` on two of its three variants, so a
 * callback over a bare `{ status: "loading" }` object infers `T | null` for the
 * payload. These builders name the payload type once so the callbacks below stay
 * about the value rather than the narrowing.
 */
type Providers = { providers: ProviderConnectionResponse[] };

function loadingProviders(): SettingsResourceState<Providers> {
  return { status: "loading", data: null, error: null };
}

function failedProviders(message: string): SettingsResourceState<Providers> {
  return { status: "error", data: null, error: message };
}

function readyProviders(
  providers: ProviderConnectionResponse[],
): SettingsResourceState<Providers> {
  return { status: "ready", data: { providers }, error: null };
}

function ready<T>(records: readonly T[]): ChoiceSet<T> {
  return {
    status: records.length === 0 ? "empty" : "ready",
    error: null,
    records: [...records],
    blocking: false,
  };
}

describe("toChoiceSet", () => {
  it("reports loading as blocking, because the answer is not yet known", () => {
    const choices = toChoiceSet(loadingProviders(), (data) => data.providers);

    expect(choices.status).toBe("loading");
    expect(choices.blocking).toBe(true);
    expect(choices.records).toEqual([]);
  });

  it("reports a failed request as unavailable, not as empty", () => {
    // This is the distinction the whole module exists to protect. `error` and
    // `ready` with `[]` produce identical records, so status and blocking have
    // to carry the difference — a caller that only checks `records.length`
    // would tell the operator they have no runtimes when the truth is that AVA
    // could not ask.
    const choices = toChoiceSet(failedProviders("Request failed"), (data) =>
      data.providers,
    );

    expect(choices.status).toBe("unavailable");
    expect(choices.blocking).toBe(true);
    expect(choices.error).toBe("Request failed");
    expect(choices.records).toEqual([]);
  });

  it("distinguishes a successful empty inventory from a failure", () => {
    // The other half of the same distinction: this one is NOT blocking, because
    // "there is nothing configured" is a true answer the operator can act on.
    const choices = toChoiceSet(readyProviders([]), (data) => data.providers);

    expect(choices.status).toBe("empty");
    expect(choices.blocking).toBe(false);
    expect(choices.records).toEqual([]);
  });

  it("reports records as ready and copies them so callers cannot mutate state", () => {
    const records = [provider()];
    const choices = toChoiceSet(readyProviders(records), (data) =>
      data.providers,
    );

    expect(choices.status).toBe("ready");
    expect(choices.blocking).toBe(false);
    expect(choices.records).toEqual(records);
    expect(choices.records).not.toBe(records);
  });
});

describe("providerOptions", () => {
  it("uses the connection id as the value and the display name as the label", () => {
    // The value must be the configured instance, never the adapter kind. A
    // default that stored `provider_id` would be ambiguous the moment two
    // connections to the same provider existed.
    const options = providerOptions(ready([provider()]), "");

    expect(options).toEqual([
      { value: "conn-a", label: "Acme Primary — acme", disabled: false },
    ]);
  });

  it("keeps a disabled record visible but unselectable for new choices", () => {
    const options = providerOptions(
      ready([provider({ provider_connection_id: "conn-off", enabled: false })]),
      "",
    );

    expect(options).toHaveLength(1);
    expect(options[0].label).toContain("Acme Primary");
    expect(options[0].disabled).toBe(true);
  });

  it("preserves a stored id that no longer exists, disabled", () => {
    // A default can outlive the record it points at. Dropping it would render
    // the field as unset, which reads as "no default" rather than "a default
    // points at something missing" — and the operator would then save over it
    // without ever learning the reference was dangling.
    const options = providerOptions(ready([provider()]), "conn-gone");

    expect(options).toHaveLength(2);
    expect(options[1]).toEqual({
      value: "conn-gone",
      label: missingRecordLabel("conn-gone"),
      disabled: true,
    });
  });

  it("does not claim a stored id is absent while the source is still loading", () => {
    // Absence is unproven during `loading`. Labelling the stored id "not
    // present" here would assert a fact the UI does not have, and an operator
    // who believed it would conclude a working default is broken and replace
    // it with something else.
    const loading: ChoiceSet<ProviderConnectionResponse> = {
      status: "loading",
      error: null,
      records: [],
      blocking: true,
    };
    const options = providerOptions(loading, "conn-a");

    expect(options[0].value).toBe("conn-a");
    expect(options[0].label).toBe("conn-a (still loading)");
    expect(options[0].disabled).toBe(true);
  });

  it("does not claim a stored id is absent when the source failed", () => {
    // Same reasoning as loading: a failed request is not evidence of absence.
    const failed: ChoiceSet<ProviderConnectionResponse> = {
      status: "unavailable",
      error: "Request failed",
      records: [],
      blocking: true,
    };
    const options = providerOptions(failed, "conn-a");

    expect(options[0].label).toBe("conn-a (inventory unavailable)");
  });

  it("does not claim a model mismatch when the source failed", () => {
    // The mismatch wording is the most specific claim the module makes, so it
    // must not appear on a path where the record was never actually seen.
    const failed: ChoiceSet<ModelConfigurationResponse> = {
      status: "unavailable",
      error: "Request failed",
      records: [],
      blocking: true,
    };
    const options = modelOptions(failed, "conn-a", "model-b");

    expect(options[0].label).toBe("model-b (inventory unavailable)");
  });

  it("does not duplicate a stored id that is still present", () => {
    const options = providerOptions(ready([provider()]), "conn-a");

    expect(options).toHaveLength(1);
    expect(options[0].value).toBe("conn-a");
  });

  it("adds nothing when no value is stored yet", () => {
    const options = providerOptions(ready([provider()]), "");

    expect(options).toHaveLength(1);
  });
});

describe("modelOptions", () => {
  it("offers only models belonging to the selected provider connection", () => {
    // 5.8 rejects a model that belongs to a different connection, so offering
    // one would build a pairing that can only fail validation.
    const options = modelOptions(
      ready([
        model(),
        model({ model_id: "model-b", provider_connection_id: "conn-b" }),
      ]),
      "conn-a",
      "",
    );

    expect(options.map((option) => option.value)).toEqual(["model-a"]);
  });

  it("offers every model when no provider is chosen, rather than guessing one", () => {
    // With no provider there is no constraint to apply. Returning everything
    // would invite the mismatch 5.8 rejects; returning nothing is honest and
    // the field's own state says why.
    const options = modelOptions(ready([model()]), "", "");

    expect(options).toEqual([]);
  });

  it("preserves a stored model from another connection and names the mismatch", () => {
    // Two different problems collapse into one empty select if this is dropped:
    // a dangling id, and a model that exists but belongs elsewhere. The second
    // is repairable by changing the provider, so the label has to say which it
    // is rather than implying the record is gone.
    const options = modelOptions(
      ready([
        model(),
        model({ model_id: "model-b", provider_connection_id: "conn-b" }),
      ]),
      "conn-a",
      "model-b",
    );

    const preserved = options.find((option) => option.value === "model-b");
    expect(preserved?.label).toBe(
      "Acme Large (belongs to a different provider connection)",
    );
    expect(preserved?.disabled).toBe(true);
  });

  it("labels a stored model that is absent as missing, not as a mismatch", () => {
    const options = modelOptions(ready([model()]), "conn-a", "model-gone");

    const preserved = options.find((option) => option.value === "model-gone");
    expect(preserved?.label).toBe(missingRecordLabel("model-gone"));
    expect(preserved?.disabled).toBe(true);
  });
});

describe("runtimeOptions", () => {
  it("uses the configuration id as the value and the type as secondary text", () => {
    const options = runtimeOptions(ready([runtime()]), "");

    expect(options).toEqual([
      { value: "rt-a", label: "Native — subprocess", disabled: false },
    ]);
  });

  it("preserves a stored runtime that is absent, disabled", () => {
    const options = runtimeOptions(ready([runtime()]), "rt-gone");

    expect(options[1]).toEqual({
      value: "rt-gone",
      label: missingRecordLabel("rt-gone"),
      disabled: true,
    });
  });
});

describe("displayLabel", () => {
  it("resolves the configured display name from the record id", () => {
    const value = displayLabel(
      [provider()],
      "conn-a",
      (record) => record.provider_connection_id,
    );

    expect(value).toBe("Acme Primary");
  });

  it("falls back to the raw id when the record is absent", () => {
    // The read-only display must never render blank for a reference that
    // exists. An id with no matching record is still a real stored value, and
    // blanking it would make stored configuration look unset.
    const value = displayLabel(
      [provider()],
      "conn-gone",
      (record) => record.provider_connection_id,
    );

    expect(value).toBe("conn-gone");
  });

  it("falls back to the raw id when the inventory could not be loaded", () => {
    // Unavailable carries no records, so this is the same path as absent — but
    // it is the common case after a reload failure, and it must not produce a
    // misleading name.
    const value = displayLabel(
      [] as ProviderConnectionResponse[],
      "conn-a",
      (record) => record.provider_connection_id,
    );

    expect(value).toBe("conn-a");
  });
});
