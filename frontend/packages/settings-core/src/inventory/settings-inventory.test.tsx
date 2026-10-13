import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsInventory } from "./SettingsInventory";

describe("SettingsInventory appearance", () => {
  it("uses a black provider/configuration surface with readable text in Dark mode", () => {
    const html = renderToStaticMarkup(
      <SettingsInventory
        label="Configured provider connections"
        entries={[{
          id: "ollama-local",
          title: "Ollama Local",
          association: "ollama-local",
          metadata: "local · http://localhost:11434/v1",
          enabled: true,
        }]}
      />,
    );
    expect(html).toContain("bg-card");
    expect(html).toContain("dark:bg-black");
    expect(html).toContain("dark:text-white");
    expect(html).toContain("dark:text-white/80");
  });
});
