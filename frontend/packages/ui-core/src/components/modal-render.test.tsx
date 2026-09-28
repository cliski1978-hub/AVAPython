// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Modal } from "./Modal";
import { AppShell } from "./AppShell";

/**
 * Static render-contract checks.
 *
 * The dialog renders through a portal, which `renderToStaticMarkup` cannot
 * produce, so only the closed case is asserted here. The open-state markup and
 * all interactive behaviour are covered in `modal.test.tsx` (jsdom) and again
 * through the `SettingsModal` wrapper in `@ava/settings-core`.
 *
 * The AppShell cases below keep the ui-core convention of static-markup tests.
 */

describe("Modal render contract", () => {
  it("renders nothing when closed", () => {
    const html = renderToStaticMarkup(
      <Modal open={false} title="Add Provider" onClose={() => {}}>
        <p>Body</p>
      </Modal>,
    );
    expect(html).toBe("");
  });
  // The open-state markup is asserted in modal.test.tsx: a portal cannot be
  // server-rendered, and in settings-core through the SettingsModal wrapper.
});

describe("AppShell sidebar", () => {
  it("shows the sidebar by default", () => {
    const html = renderToStaticMarkup(
      <AppShell mainContent={<p>Main</p>} sidebarChildren={<p>Conversations</p>} />,
    );
    expect(html).toContain("<aside");
    expect(html).toContain("Conversations");
  });

  it("omits the sidebar entirely when showSidebar is false", () => {
    const html = renderToStaticMarkup(
      <AppShell
        mainContent={<p>Main</p>}
        sidebarChildren={<p>Conversations</p>}
        showSidebar={false}
      />,
    );
    expect(html).not.toContain("<aside");
    expect(html).not.toContain("Conversations");
    expect(html).toContain("Main");
  });
});
