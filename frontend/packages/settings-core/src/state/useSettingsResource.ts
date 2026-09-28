import { useCallback, useEffect, useRef, useState } from "react";

import { settingsErrorMessage } from "./settingsErrorMessage";

/**
 * The single asynchronous data primitive for the Settings surface.
 *
 * Every Settings section loads through this hook, so loading, error, empty, and
 * retry behaviour is defined once rather than four times. It deliberately adds
 * no state library and no cache: a Settings screen reads a handful of small
 * lists, and the management phases (5.12-5.15) mutate through an explicit
 * reload after a successful write.
 *
 * A generation counter discards responses from superseded requests, so a retry
 * that lands after a slower earlier request cannot overwrite fresher data.
 */

export type SettingsResourceState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

export interface SettingsResource<T> {
  state: SettingsResourceState<T>;
  /** Re-runs the loader, keeping the current data visible while it does. */
  reload: () => void;
}

export interface UseSettingsResourceOptions {
  /** Set false to skip loading entirely (for example an unmounted section). */
  enabled?: boolean;
}

export function useSettingsResource<T>(
  load: () => Promise<T>,
  options: UseSettingsResourceOptions = {},
): SettingsResource<T> {
  const { enabled = true } = options;

  const [state, setState] = useState<SettingsResourceState<T>>({
    status: "loading",
    data: null,
    error: null,
  });
  const [attempt, setAttempt] = useState(0);
  const generationRef = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled) return;

    const generation = generationRef.current + 1;
    generationRef.current = generation;

    let cancelled = false;
    setState((previous) =>
      previous.status === "ready"
        ? // Keep existing data visible during a reload so the section does
          // not collapse back to a loading skeleton.
          { status: "ready", data: previous.data, error: null }
        : { status: "loading", data: null, error: null },
    );

    void (async () => {
      try {
        const data = await loadRef.current();
        if (cancelled || generationRef.current !== generation) return;
        setState({ status: "ready", data, error: null });
      } catch (error) {
        if (cancelled || generationRef.current !== generation) return;
        setState({
          status: "error",
          data: null,
          error: settingsErrorMessage(error),
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [attempt, enabled]);

  const reload = useCallback(() => {
    setAttempt((previous) => previous + 1);
  }, []);

  return { state, reload };
}
