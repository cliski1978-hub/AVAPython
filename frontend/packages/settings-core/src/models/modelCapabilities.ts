import { CONTRACT_VERSION } from "@ava/contracts";
import type { ContractVersion, ModelCapabilities } from "@ava/contracts";

/**
 * The capability vocabulary, read straight from `ModelCapabilities`.
 *
 * `ModelCapabilities` is a typed boolean record, not a set of vendor feature
 * names and not free-form JSON. Phase 5.4 fixed these eight flags as
 * provider-neutral declared configuration, and Phase 5.12 confirmed there is no
 * settings-side precedent for editing them. So the UI offers exactly these
 * eight checkboxes and nothing else: no invented flag, no dynamic key, no
 * passthrough editor.
 *
 * The flags are declared, not measured. Nothing here implies that a capability
 * is permitted, available, or qualified — qualification is separate measured
 * evidence keyed by `model_id` and is not editable configuration.
 */

type CapabilityKey = {
  [K in keyof ModelCapabilities]: ModelCapabilities[K] extends boolean ? K : never;
}[keyof ModelCapabilities] &
  string;

interface CapabilityField {
  key: CapabilityKey;
  /** Operator-facing name for the flag. */
  label: string;
  /** Short form for the inventory's capability summary. */
  short: string;
}

/** Display order: general purpose first, then specialised. */
export const CAPABILITY_FIELDS: readonly CapabilityField[] = [
  { key: "chat", label: "Chat", short: "chat" },
  { key: "streaming", label: "Streaming", short: "stream" },
  { key: "tool_calling", label: "Tool calling", short: "tools" },
  { key: "structured_output", label: "Structured output", short: "json" },
  { key: "vision", label: "Vision", short: "vision" },
  { key: "embeddings", label: "Embeddings", short: "embed" },
  { key: "reasoning", label: "Reasoning", short: "reason" },
  { key: "code_specialization", label: "Code specialization", short: "code" },
];

/**
 * Build a capabilities object with every flag off.
 *
 * The backend defaults every flag to `False` — a capability is only true when
 * the model is known to support it — so an untouched new form sends a
 * conservative record rather than guessing. `contract_version` is carried
 * through rather than hard-coded per call, so an edit round-trips the version it
 * was given instead of inventing one.
 */
export function emptyCapabilities(
  version: ContractVersion = CONTRACT_VERSION,
): ModelCapabilities {
  return {
    chat: false,
    streaming: false,
    tool_calling: false,
    structured_output: false,
    vision: false,
    embeddings: false,
    reasoning: false,
    code_specialization: false,
    contract_version: version,
  };
}

/** A form-friendly view: one boolean per flag, keyed by the contract's own names. */
export type CapabilityToggles = Record<CapabilityKey, boolean>;

/** Read a contract object into toggles, defaulting any unknown flag to off. */
export function capabilityToggles(
  capabilities: ModelCapabilities,
): CapabilityToggles {
  const toggles = {} as CapabilityToggles;
  for (const field of CAPABILITY_FIELDS) {
    toggles[field.key] = capabilities[field.key];
  }
  return toggles;
}

/** Build a contract object from toggles, preserving the declared version. */
export function capabilitiesFrom(
  toggles: CapabilityToggles,
  version: ContractVersion = CONTRACT_VERSION,
): ModelCapabilities {
  return { ...emptyCapabilities(version), ...toggles, contract_version: version };
}

/** Every flag that is on, in display order. */
export function enabledCapabilityKeys(
  capabilities: ModelCapabilities,
): CapabilityKey[] {
  return CAPABILITY_FIELDS.filter((field) => capabilities[field.key]).map(
    (field) => field.key,
  );
}

/**
 * One concise line for the inventory, e.g. `chat · stream · tools`.
 *
 * A model with nothing declared is a real state, not an omission, so it is
 * stated rather than left blank.
 */
export function capabilitySummary(capabilities: ModelCapabilities): string {
  const short = CAPABILITY_FIELDS.filter((field) => capabilities[field.key]).map(
    (field) => field.short,
  );
  return short.length === 0 ? "No declared capabilities" : short.join(" · ");
}
