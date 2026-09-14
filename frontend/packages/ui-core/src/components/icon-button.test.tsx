import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IconButton } from "./IconButton";

describe("IconButton", () => {
  it("renders the required accessible label and native tooltip", () => {
    const html = renderToStaticMarkup(
      <IconButton ariaLabel="Collapse sidebar" title="Collapse sidebar">
        «
      </IconButton>,
    );
    expect(html).toContain('aria-label="Collapse sidebar"');
    expect(html).toContain('title="Collapse sidebar"');
    expect(html).toContain(">«</button>");
  });

  it("passes through a disabled state", () => {
    const html = renderToStaticMarkup(
      <IconButton ariaLabel="Copy" disabled>
        copy
      </IconButton>,
    );
    expect(html).toContain('disabled=""');
  });
});