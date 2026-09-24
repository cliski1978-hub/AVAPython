import { Button, defaultTheme, IconButton, Textarea } from "@ava/ui-core";
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import {
  enterShouldSubmit,
  isMeaningfulPrompt,
  rowsForPrompt,
} from "../lib/prompt";

export interface PromptComposerProps {
  /**
   * Controlled value. When provided, the composer is fully controlled: the
   * parent owns the text and is expected to clear it after a successful
   * submit. When omitted, the composer manages its own draft text and clears
   * it after a successful submit.
   */
  value?: string;
  /** Called on every edit in both controlled and self-managed modes. */
  onChange?: (value: string) => void;
  /** Called with the trimmed prompt once meaningful content is submitted. */
  onSubmit: (prompt: string) => void | Promise<void>;
  /** Called when the user activates the Stop action while running. */
  onStop: () => void;
  /** True while a run is active with a backend run id (Stop is enabled). */
  isRunning?: boolean;
  /** True while the run id is still being created (Send and Stop disabled). */
  isStarting?: boolean;
  /** True while a cancellation request is in flight (Stop disabled). */
  isStopping?: boolean;
  /** Disables editing and all actions. */
  disabled?: boolean;
  placeholder?: string;
  minRows?: number;
  maxRows?: number;
  controls?: ReactNode;
}

const t = defaultTheme;

export function PromptComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  isRunning = false,
  isStarting = false,
  isStopping = false,
  disabled = false,
  placeholder,
  minRows = 1,
  maxRows = 6,
  controls,
}: PromptComposerProps) {
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");

  const controlled = value !== undefined;
  const text = controlled ? value : draft;

  const update = (next: string) => {
    if (!controlled) {
      draftRef.current = next;
      setDraft(next);
    }
    onChange?.(next);
  };

  const inFlight = isRunning || isStarting || isStopping;

  const handleSubmit = () => {
    if (disabled || inFlight) return;
    if (!isMeaningfulPrompt(text)) return;
    const prompt = text.trim();
    let outcome: void | Promise<void>;
    try {
      outcome = onSubmit(prompt);
    } catch {
      return;
    }
    Promise.resolve(outcome).catch(() => {
      if (!controlled && draftRef.current === "") {
        update(prompt);
      }
    });
    update("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      enterShouldSubmit({
        key: event.key,
        shiftKey: event.shiftKey,
        isComposing: event.nativeEvent.isComposing,
      })
    ) {
      event.preventDefault();
      handleSubmit();
    }
  };

  const rows = rowsForPrompt(text, minRows, maxRows);
  const canSend = !disabled && !inFlight && isMeaningfulPrompt(text);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: t.spacing.xs,
        padding: t.spacing.sm,
        border: `${t.border.width}px solid ${
          disabled ? t.colors.border : t.colors.borderStrong
        }`,
        borderRadius: t.radius.lg,
        background: disabled ? t.colors.disabledBg : t.colors.surface,
        transition: "border-color 120ms ease, background 120ms ease",
        boxSizing: "border-box",
        position: "relative",
      }}
      data-prompt-composer=""
    >
      <div style={{ display: "flex", alignItems: "flex-end", gap: t.spacing.sm }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Textarea value={text} onChange={update} onKeyDown={handleKeyDown} rows={rows} placeholder={placeholder} disabled={disabled} ariaLabel="Message" />
        </div>
        {!inFlight && (
          <Button variant="primary" disabled={!canSend} ariaLabel="Send" title={canSend ? "Send message" : "Type a message to send a prompt"} onClick={handleSubmit}
            style={{ flex: "0 0 34px", width: 34, height: 34, marginBottom: 10, padding: 0, borderRadius: "50%", background: "#174a9c", borderColor: "#174a9c", fontSize: 20, lineHeight: 1 }}
          >↑</Button>
        )}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          minHeight: t.control.height,
        }}
      >
        {isStarting || isStopping ? (
          <span
            data-composer-status=""
            role="status"
            style={{ fontSize: t.font.sizeSm, color: t.colors.mutedText }}
          >
            {isStarting ? "Starting…" : "Stopping…"}
          </span>
        ) : (
          <IconButton
            ariaLabel="Attach file"
            title="Attachments are not available yet"
            disabled
            size="sm"
          >
            +
          </IconButton>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: t.spacing.sm }}>
        {controls}
        {inFlight ? (
          <Button
            variant="danger"
            disabled={disabled || !isRunning}
            ariaLabel="Stop"
            title={
              isStarting
                ? "Starting — Stop unavailable"
                : isStopping
                  ? "Stopping…"
                  : "Stop responding"
            }
            onClick={onStop}
          >
            Stop
          </Button>
        ) : null}
        </div>
      </div>
    </div>
  );
}
