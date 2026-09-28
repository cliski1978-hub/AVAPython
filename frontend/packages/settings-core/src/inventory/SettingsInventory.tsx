import { StatusIndicator, defaultTheme } from "@ava/ui-core";
import type { ReactNode } from "react";

/**
 * Read-only inventory presentation for persisted configuration records.
 *
 * Deliberately a list of rows, not a data grid. The three inventories a
 * Settings screen shows (providers, models, runtimes) have a handful of rows
 * each, and the management phases add an action slot per row rather than
 * column sorting or filtering. Over-designing a grid here would be work the
 * later phases would immediately have to work around.
 *
 * Each row takes an already-shaped descriptor so the four sections own their
 * own domain wording and this pattern stays free of domain knowledge.
 *
 * Disabled records are rendered by the sections, never filtered: a record a
 * user configured must stay visible so it can be found and re-enabled later.
 */

const t = defaultTheme;

export interface SettingsInventoryEntry {
  /** Stable configured identity, shown verbatim so it can be copied. */
  id: string;
  /** Human label, typically the configured display name. */
  title: string;
  /** Type or provider association line, e.g. `openai` or `native`. */
  association?: string;
  /** Concise secondary metadata, e.g. an endpoint or credential reference. */
  metadata?: string;
  /**
   * Optional third line for a compact attribute summary, e.g. declared model
   * capabilities. Omitted rather than blank when a record has nothing to say.
   */
  details?: string;
  enabled: boolean;
}

export interface SettingsInventoryProps {
  /** Accessible name for the list, e.g. "Configured provider connections". */
  label: string;
  entries: SettingsInventoryEntry[];
  /**
   * Per-row actions. Supplied by the providers and models sections, whose rows
   * are editable. Omitted by the read-only sections (runtimes, defaults).
   *
   * Only the actions a section actually offers belong here. Delete and
   * deliberately remain absent: configuration records are retired by being
   * disabled, so that they stay findable and re-enablable.
   */
  renderActions?: (entry: SettingsInventoryEntry) => ReactNode;
  /** Monospace emphasis for the id, appropriate for configured identities. */
  monospaceId?: boolean;
}

function EntryStatus({ enabled }: { enabled: boolean }) {
  return (
    <StatusIndicator
      state={enabled ? "success" : "neutral"}
      label={enabled ? "Enabled" : "Disabled"}
    />
  );
}

export function SettingsInventory({
  label,
  entries,
  renderActions,
  monospaceId = true,
}: SettingsInventoryProps) {
  return (
    <ul
      aria-label={label}
      data-testid="settings-inventory"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: t.spacing.sm,
        margin: 0,
        padding: 0,
        listStyle: "none",
      }}
    >
      {entries.map((entry) => (
        <li
          key={entry.id}
          data-testid="settings-inventory-entry"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: t.spacing.md,
            padding: `${t.spacing.md}px ${t.spacing.lg}px`,
            border: `${t.border.width}px solid ${t.colors.border}`,
            borderRadius: t.radius.lg,
            background: t.colors.background,
            boxSizing: "border-box",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 2,
              minWidth: 0,
            }}
          >
            <span
              style={{
                fontSize: t.font.sizeSm,
                fontWeight: t.font.weightSemibold,
                color: t.colors.foreground,
              }}
            >
              {entry.title}
            </span>
            <span
              data-testid="settings-inventory-entry-id"
              title={entry.id}
              style={{
                fontSize: t.font.sizeXs,
                fontFamily: monospaceId
                  ? "ui-monospace, SFMono-Regular, Menlo, monospace"
                  : t.font.family,
                color: t.colors.mutedText,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {entry.id}
            </span>
            {(entry.association != null || entry.metadata != null) && (
              <span
                data-testid="settings-inventory-entry-meta"
                title={
                  entry.association != null && entry.metadata != null
                    ? `${entry.association} · ${entry.metadata}`
                    : (entry.association ?? entry.metadata)
                }
                style={{
                  fontSize: t.font.sizeXs,
                  fontFamily: t.font.family,
                  color: t.colors.mutedText,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {entry.association != null && entry.metadata != null
                  ? `${entry.association} · ${entry.metadata}`
                  : (entry.association ?? entry.metadata)}
              </span>
            )}
            {entry.details != null && (
              <span
                data-testid="settings-inventory-entry-details"
                title={entry.details}
                style={{
                  fontSize: t.font.sizeXs,
                  fontFamily: t.font.family,
                  color: t.colors.mutedText,
                  opacity: 0.85,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {entry.details}
              </span>
            )}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: t.spacing.md,
              flexShrink: 0,
            }}
          >
            <EntryStatus enabled={entry.enabled} />
            {renderActions?.(entry)}
          </div>
        </li>
      ))}
    </ul>
  );
}
