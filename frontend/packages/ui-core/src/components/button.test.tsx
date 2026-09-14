import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("renders children and defaults to a standard button type", () => {
    const html = renderToStaticMarkup(<Button>Save</Button>);
    expect(html).toContain(">Save</span>");
    expect(html).toContain('type="button"');
    expect(html).not.toContain('disabled=""');
  });

  it("disables the native button when disabled and styles it as disabled", () => {
    const html = renderToStaticMarkup(<Button disabled>Save</Button>);
    expect(html).toContain('disabled=""');
    expect(html).toContain("cursor:not-allowed");
  });

  it("renders a loading spinner and disables interaction when loading", () => {
    const html = renderToStaticMarkup(<Button loading>Save</Button>);
    expect(html).toContain('disabled=""');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('role="status"');
    expect(html).toContain(">Save</span>");
  });

  it("exposes its variant for styling and testing", () => {
    const html = renderToStaticMarkup(
      <Button variant="primary">Save</Button>,
    );
    expect(html).toContain('data-variant="primary"');
  });

  it("uses explicit border longhands to avoid React shorthand warnings", () => {
    const html = renderToStaticMarkup(<Button variant="primary">Save</Button>);
    expect(html).toContain("border-width:1px");
    expect(html).toContain("border-style:solid");
    expect(html).toContain("border-color:#2563eb");
    expect(html).not.toMatch(/style="[^"]*\bborder:\s/);
  });
});