import { useState } from "react";

import { settingsErrorMessage } from "./settingsErrorMessage";

/**
 * The submit lifecycle every Settings form needs.
 *
 * Phase 5.12 proved this sequence for provider connections; models (5.13),
 * runtimes (5.14), and defaults (5.15) need the same one. It lives here so the
 * surface has exactly one implementation of "hold the values, clear a field's
 * error when it is edited, validate before sending, refuse a second submit,
 * refuse dismissal mid-flight, and map a failure to a safe sentence" — rather
 * than four copies that drift.
 *
 * All state is local `useState`. There is no store, no cache, and nothing
 * outlives the dialog: the editor unmounts on close, and the Settings surface
 * itself unmounts when the user navigates away.
 */

export type SettingsFormErrors<TValues> = Partial<Record<keyof TValues, string>>;

export interface SettingsFormOptions<TValues extends object> {
  initial: TValues;
  /** Return a field-keyed error map; an empty map means the form may be sent. */
  validate: (values: TValues) => SettingsFormErrors<TValues>;
  /**
   * Perform the write. Throwing is how a failure is reported: the hook catches
   * it, maps it to a safe sentence, and leaves the dialog open.
   */
  perform: (values: TValues) => Promise<void>;
  /** Called after a successful write. */
  onSaved: () => void;
  /** Called when the operator dismisses the dialog. */
  onClose: () => void;
  /** Shown when a failure carries no backend message of its own. */
  fallbackMessage: string;
}

export interface SettingsForm<TValues extends object> {
  values: TValues;
  errors: SettingsFormErrors<TValues>;
  /** Update one field and clear that field's error if it had one. */
  set: <K extends keyof TValues>(key: K, value: TValues[K]) => void;
  submitError: string | null;
  busy: boolean;
  /** Validate, then write. Safe to call from a click or a form submit. */
  save: () => Promise<void>;
  /** Dismissal that refuses while a write is in flight. */
  requestClose: () => void;
}

export function useSettingsForm<TValues extends object>({
  initial,
  validate,
  perform,
  onSaved,
  onClose,
  fallbackMessage,
}: SettingsFormOptions<TValues>): SettingsForm<TValues> {
  const [values, setValues] = useState<TValues>(initial);
  const [errors, setErrors] = useState<SettingsFormErrors<TValues>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof TValues>(key: K, value: TValues[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (current[key] == null) {
        return current;
      }
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const save = async () => {
    if (busy) {
      return;
    }

    const found = validate(values);
    setErrors(found);
    setSubmitError(null);
    if (Object.keys(found).length > 0) {
      return;
    }

    setBusy(true);
    try {
      await perform(values);
      onSaved();
    } catch (thrown) {
      // The dialog stays open with the operator's input intact, and the message
      // is the backend's designed ErrorResponse text (or a fixed fallback)
      // rather than a raw thrown value.
      setSubmitError(settingsErrorMessage(thrown, fallbackMessage));
    } finally {
      setBusy(false);
    }
  };

  const requestClose = () => {
    // Refused while a write is in flight, so Escape, an overlay click, or a
    // cancel button cannot discard a submit that is still running. This is the
    // editor's own guard: `Modal` does not suppress dismissal on its own.
    if (busy) {
      return;
    }
    onClose();
  };

  return { values, errors, set, submitError, busy, save, requestClose };
}
