import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Header } from "./Header";

describe("Header", () => {
  it("uses the AVA wordmark for its default brand title", () => {
    const html = renderToStaticMarkup(<Header />);

    expect(html).toContain('data-ava-brand-mark=""');
    expect(html).toContain('alt="AVA"');
  });

  it("preserves non-brand page titles", () => {
    const html = renderToStaticMarkup(<Header title="Settings" />);

    expect(html).toContain(">Settings</h1>");
    expect(html).not.toContain("data-ava-brand-mark");
  });
});
