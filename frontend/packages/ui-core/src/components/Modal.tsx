import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

/**
 * The single dialog primitive for AVA.
 *
 * There is exactly one modal system in the frontend. Feature packages compose
 * this rather than implementing their own, so focus management, Escape
 * handling, and overlay behaviour cannot drift between features.
 *
 * Accessibility contract:
 *  - `role="dialog"` + `aria-modal="true"` + `aria-labelledby`
 *  - focus moves into the dialog on open and is restored to the previously
 *    focused element on close
 *  - Tab and Shift+Tab cycle within the dialog (focus trap)
 *  - Escape and overlay click request a close
 *  - background scroll is locked while open
 *
 * The component renders nothing when `open` is false, so a caller can keep a
 * single instance mounted and toggle it.
 */

export interface ModalProps {
  open: boolean;
  title: ReactNode;
  children: ReactNode;
  /** Primary action label. Omit to render a close-only dialog. */
  primaryAction?: ReactNode;
  onPrimaryAction?: () => void;
  /** Secondary/cancel action label. Omit to hide the secondary button. */
  secondaryAction?: ReactNode;
  onSecondaryAction?: () => void;
  /** Renders the primary action as busy and blocks dismissal-by-primary. */
  primaryBusy?: boolean;
  primaryDisabled?: boolean;
  onClose: () => void;
  /** Dismiss when the backdrop is clicked. Defaults to true. */
  closeOnOverlayClick?: boolean;
  /** Dismiss on Escape. Defaults to true. */
  closeOnEscape?: boolean;
  width?: number;
}

const t = defaultTheme;

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter(
    (element) =>
      !element.hasAttribute("disabled") &&
      element.getAttribute("aria-hidden") !== "true",
  );
}

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: t.spacing.lg,
  background: "rgba(17, 24, 39, 0.45)",
  zIndex: 1000,
  boxSizing: "border-box",
};

const dialogStyle = (width: number): CSSProperties => ({
  display: "flex",
  flexDirection: "column",
  width: "100%",
  maxWidth: width,
  maxHeight: "100%",
  background: t.colors.background,
  borderRadius: t.radius.lg,
  boxShadow: "0 16px 40px rgba(17, 24, 39, 0.24)",
  boxSizing: "border-box",
  outline: "none",
  overflow: "hidden",
});

export function Modal({
  open,
  title,
  children,
  primaryAction,
  onPrimaryAction,
  secondaryAction,
  onSecondaryAction,
  primaryBusy = false,
  primaryDisabled = false,
  onClose,
  closeOnOverlayClick = true,
  closeOnEscape = true,
  width = 480,
}: ModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  const requestClose = useCallback(() => {
    closeRef.current();
  }, []);

  // Move focus into the dialog on open, restore it on close.
  useEffect(() => {
    if (!open) return;

    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const dialog = dialogRef.current;
    if (dialog != null) {
      const first = focusableWithin(dialog)[0];
      (first ?? dialog).focus();
    }

    return () => {
      const restore = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (restore != null && restore.isConnected) {
        restore.focus();
      }
    };
  }, [open]);

  // Lock background scroll while open.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Escape closes; Tab is trapped inside the dialog.
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && closeOnEscape) {
        event.preventDefault();
        requestClose();
        return;
      }

      if (event.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (dialog == null) return;

      const focusable = focusableWithin(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (event.shiftKey) {
        if (active === first || active === dialog) {
          event.preventDefault();
          last.focus();
        }
        return;
      }

      if (active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, closeOnEscape, requestClose]);

  const closeInteraction = useInteraction(true);

  if (!open || typeof document === "undefined") return null;

  const closeButtonStyle: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 28,
    height: 28,
    marginRight: t.spacing.sm,
    borderRadius: t.radius.sm,
    border: "none",
    background: "transparent",
    color: t.colors.mutedText,
    fontSize: 18,
    lineHeight: 1,
    cursor: "pointer",
    outline: "none",
    flexShrink: 0,
    transition: "background 120ms ease, color 120ms ease",
    ...(closeInteraction.hovered
      ? { background: t.colors.ghostHover, color: t.colors.foreground }
      : {}),
    ...(closeInteraction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}66` }
      : {}),
  };

  const footerStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: t.spacing.sm,
    padding: `${t.spacing.md}px ${t.spacing.lg}px`,
    borderTop: `${t.border.width}px solid ${t.colors.border}`,
    background: t.colors.surface,
    flexShrink: 0,
  };

  return createPortal(
    <div
      style={overlayStyle}
      onClick={closeOnOverlayClick ? requestClose : undefined}
      data-testid="modal-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={dialogStyle(width)}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: t.spacing.sm,
            padding: `${t.spacing.md}px ${t.spacing.lg}px`,
            borderBottom: `${t.border.width}px solid ${t.colors.border}`,
            flexShrink: 0,
          }}
        >
          <h2
            id={titleId}
            style={{
              margin: 0,
              fontSize: t.font.sizeMd,
              fontWeight: t.font.weightSemibold,
              color: t.colors.foreground,
            }}
          >
            {title}
          </h2>
          <button
            type="button"
            aria-label="Close dialog"
            style={closeButtonStyle}
            onClick={requestClose}
            onMouseEnter={closeInteraction.onMouseEnter}
            onMouseLeave={closeInteraction.onMouseLeave}
            onFocus={closeInteraction.onFocus}
            onBlur={closeInteraction.onBlur}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        <div
          style={{
            flex: 1,
            overflow: "auto",
            padding: t.spacing.lg,
            display: "flex",
            flexDirection: "column",
            gap: t.spacing.md,
          }}
        >
          {children}
        </div>

        {(primaryAction != null || secondaryAction != null) && (
          <div style={footerStyle}>
            {secondaryAction != null && (
              <button
                type="button"
                disabled={primaryBusy}
                style={{
                  height: t.control.height,
                  padding: `0 ${t.spacing.lg}px`,
                  borderRadius: t.control.radius,
                  borderWidth: t.border.width,
                  borderStyle: "solid",
                  borderColor: t.colors.borderStrong,
                  background: t.colors.background,
                  color: t.colors.foreground,
                  fontSize: t.control.fontSize,
                  fontWeight: t.font.weightSemibold,
                  fontFamily: t.font.family,
                  cursor: primaryBusy ? "not-allowed" : "pointer",
                  opacity: primaryBusy ? 0.6 : 1,
                }}
                onClick={onSecondaryAction ?? requestClose}
              >
                {secondaryAction}
              </button>
            )}
            {primaryAction != null && (
              <button
                type="button"
                disabled={primaryDisabled || primaryBusy}
                aria-busy={primaryBusy || undefined}
                style={{
                  height: t.control.height,
                  padding: `0 ${t.spacing.lg}px`,
                  borderRadius: t.control.radius,
                  borderWidth: t.border.width,
                  borderStyle: "solid",
                  borderColor: t.colors.primary,
                  background: t.colors.primary,
                  color: t.colors.onPrimary,
                  fontSize: t.control.fontSize,
                  fontWeight: t.font.weightSemibold,
                  fontFamily: t.font.family,
                  cursor:
                    primaryDisabled || primaryBusy ? "not-allowed" : "pointer",
                  opacity: primaryDisabled || primaryBusy ? 0.6 : 1,
                }}
                onClick={onPrimaryAction}
              >
                {primaryAction}
              </button>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
