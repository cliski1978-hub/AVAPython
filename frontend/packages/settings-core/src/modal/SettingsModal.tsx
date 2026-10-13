import { Modal, defaultTheme, type ModalProps } from "@ava/ui-core";
import type { ReactNode } from "react";

/**
 * The Settings dialog pattern, for every future Add/Edit interaction.
 *
 * AVA has exactly one dialog primitive (`@ava/ui-core`'s `Modal`); this is a
 * thin Settings-shaped wrapper over it, not a second modal system. It fixes
 * the vocabulary the management phases share — title, body slot, primary
 * action, cancel, close, busy primary, validation area — so Add Provider, Edit
 * Model, and Edit Defaults cannot each invent a different shape.
 *
 * Modal state stays local to whichever section opens it. Each section holds
 * `useState<SettingsModalState | null>(null)` and renders this component; no
 * modal manager, no store, and no global registry. The two states a dialog can
 * be in while open are `idle` and `busy`, which is what a form needs to
 * distinguish "editable" from "submitting".
 *
 * Phase 5.11 ships the pattern with no consumer. The management phases open it
 * from their own sections; no domain form exists yet.
 */

export type SettingsModalState = "idle" | "busy";

export interface SettingsModalProps
  extends Omit<ModalProps, "onClose" | "onSecondaryAction"> {
  open: boolean;
  /** Caller-owned dismissal, e.g. `() => setModal(null)`. */
  onClose: () => void;
  onSecondaryAction?: () => void;
  /**
   * Validation or submit failure for this dialog, rendered in a dedicated
   * alert region above the actions. Keep it to an operator-facing sentence.
   */
  error?: string | null;
  children: ReactNode;
}

const t = defaultTheme;

export function SettingsModal({
  open,
  title,
  children,
  onClose,
  primaryAction,
  onPrimaryAction,
  secondaryAction = "Cancel",
  onSecondaryAction,
  primaryBusy = false,
  primaryDisabled = false,
  error,
  ...modalProps
}: SettingsModalProps) {
  return (
    <Modal
      open={open}
      title={title}
      primaryAction={primaryAction}
      onPrimaryAction={onPrimaryAction}
      secondaryAction={secondaryAction}
      onSecondaryAction={onSecondaryAction ?? onClose}
      primaryBusy={primaryBusy}
      primaryDisabled={primaryDisabled}
      onClose={onClose}
      {...modalProps}
    >
      {error != null && error !== "" ? (
        <p
          role="alert"
          data-testid="settings-modal-error"
          className="bg-destructive text-destructive-foreground"
          style={{
            margin: 0,
            padding: `${t.spacing.sm}px ${t.spacing.md}px`,
            borderRadius: t.radius.md,
            fontSize: "calc(13px * var(--ava-font-scale, 1))",
            lineHeight: 1.5,
          }}
        >
          {error}
        </p>
      ) : null}
      {children}
    </Modal>
  );
}
