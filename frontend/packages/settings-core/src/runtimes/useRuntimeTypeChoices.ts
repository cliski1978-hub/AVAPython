import { useEffect, useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { getRuntimes } from "@ava/api-client";
import type { SelectOption } from "@ava/ui-core";

/**
 * Runtime adapter kinds AVA currently has registered.
 *
 * Source: `GET /runtimes` (discovery). That endpoint reports the runtime
 * implementations currently registered in AVA's `RuntimeRegistry` — the keys
 * are `native` and `openhands` today.
 *
 * That list is a **convenience, not a constraint**, and the distinction matters
 * more here than it did for 5.12's provider type. Phase 5.6 decided the
 * persisted `runtime_type` column is `TEXT NOT NULL` with no vocabulary check,
 * precisely so the schema does not decide which runtimes are installed: a
 * `langgraph` or `agentcore` configuration is valid to store today, before any
 * code implements it. Phase 5.7 round-trips such values in both directions.
 *
 * So this hook offers registered keys as suggestions and nothing more. A type
 * that is not registered is still creatable, and — critically — nothing here
 * treats a non-registered value as an error, because the backend will not.
 * Contrast 5.13, where the `provider_connection_id` select is closed with no
 * escape hatch precisely *because* the backend does enforce that relationship.
 * Here the backend enforces nothing, so the UI enforces nothing.
 *
 * It is not the source of truth for configured runtimes — those always come
 * from `GET /settings/runtimes` — and the two datasets are never merged. An
 * installed runtime with no configuration is valid, and a configured runtime
 * whose adapter is not currently registered is also valid.
 *
 * The owning section calls this once and passes the result down, so the editor
 * issues no request of its own and opening the dialog is instant.
 */
export function useRuntimeTypeChoices(client: ApiClient): {
  /** Registered type keys, for the create select and the inventory's line. */
  options: SelectOption[];
  /** False until discovery answers with at least one registered runtime. */
  available: boolean;
  registeredTypes: string[];
  /**
   * Whether discovery is still in flight.
   *
   * Kept separate from `registeredTypes` being empty, because the two mean
   * different things: "AVA has no registered runtimes" and "we could not ask"
   * both produce an empty list, and only the first may be reported as "not
   * registered". A caller that conflates them turns a transient discovery
   * failure into a false statement about every configured runtime.
   */
  loading: boolean;
  /** True when discovery could not be reached, so the answer is unknown. */
  unavailable: boolean;
} {
  const [registered, setRegistered] = useState<
    { runtime_id: string; display_name?: string | null }[] | null
  >(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getRuntimes(client)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setUnavailable(false);
        // A registry key is unique, but the response is a list of ports and the
        // form should not offer the same type twice.
        const byId = new Map<
          string,
          { runtime_id: string; display_name?: string | null }
        >();
        for (const item of response.runtimes) {
          const info = item.runtime_info;
          if (!byId.has(info.runtime_id)) {
            byId.set(info.runtime_id, info);
          }
        }
        setRegistered(
          [...byId.values()].sort((a, b) =>
            a.runtime_id.localeCompare(b.runtime_id),
          ),
        );
      })
      .catch(() => {
        // A failure to list registered runtimes is not an error worth
        // interrupting configuration over: the type is free text either way.
        if (!cancelled) {
          setRegistered([]);
          setUnavailable(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const items = registered ?? [];
  return {
    // The option *value* is the registry key, because that is what a persisted
    // `runtime_type` is compared against. The registered display name rides
    // along as secondary text when the adapter supplies one, so the operator
    // sees "native — AVA Native Runtime" rather than a bare key.
    options: items.map((item) => ({
      value: item.runtime_id,
      label:
        item.display_name != null && item.display_name !== ""
          ? `${item.runtime_id} — ${item.display_name}`
          : item.runtime_id,
    })),
    available: items.length > 0,
    registeredTypes: items.map((item) => item.runtime_id),
    loading: registered == null,
    unavailable,
  };
}
