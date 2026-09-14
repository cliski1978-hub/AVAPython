import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { defaultTheme } from "../theme";
import { StatusIndicator, statusColor } from "./StatusIndicator";

describe("statusColor", () => {
  it("maps each generic state to a stable theme token", () => {
    expect(statusColor("success")).toBe(defaultTheme.colors.success);
    expect(statusColor("warning")).toBe(defaultTheme.colors.warning);
    expect(statusColor("error")).toBe(defaultTheme.colors.error);
    expect(statusColor("working")).toBe(defaultTheme.colors.working);
    expect(statusColor("neutral")).toBe(defaultTheme.colors.neutral);
  });
});

describe("StatusIndicator", () => {
  it("renders its display label with the given state", () => {
    const html = renderToStaticMarkup(
      <StatusIndicator state="success" label="Connected" />,
    );
    expect(html).toContain("Connected");
    expect(html).toContain('data-status-state="success"');
  });

  it("does not emit the label when showLabel is false", () => {
    const html = renderToStaticMarkup(
      <StatusIndicator state="neutral" label="Hidden" showLabel={false} />,
    );
    expect(html).not.toContain("Hidden");
    expect(html).toContain('data-status-state="neutral"');
  });

  it("renders a busy indicator for the working state", () => {
    const html = renderToStaticMarkup(
      <StatusIndicator state="working" label="Generating…" />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain("Generating…");
  });
});