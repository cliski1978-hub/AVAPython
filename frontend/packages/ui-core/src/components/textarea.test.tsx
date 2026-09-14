import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Textarea } from "./Textarea";

describe("Textarea", () => {
  it("applies a disabled state to the native control", () => {
    const html = renderToStaticMarkup(<Textarea disabled />);
    expect(html).toContain('disabled=""');
  });

  it("applies a readOnly state to the native control", () => {
    const html = renderToStaticMarkup(<Textarea readOnly />);
    expect(html).toContain('readonly=""');
  });

  it("renders placeholder and accessible labeling", () => {
    const html = renderToStaticMarkup(
      <Textarea placeholder="Send a message…" ariaLabel="Message" rows={2} />,
    );
    expect(html).toContain('placeholder="Send a message…"');
    expect(html).toContain('aria-label="Message"');
    expect(html).toContain('rows="2"');
  });

  it("renders a visible label when provided", () => {
    const html = renderToStaticMarkup(<Textarea label="Prompt" />);
    expect(html).toContain("<label");
    expect(html).toContain("Prompt");
  });

  it("uses explicit border longhands to avoid React shorthand warnings", () => {
    const html = renderToStaticMarkup(<Textarea />);
    expect(html).toContain("border-width:1px");
    expect(html).toContain("border-style:solid");
    expect(html).not.toMatch(/style="[^"]*\bborder:\s/);
  });
});