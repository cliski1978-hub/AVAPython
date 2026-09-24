import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = join(import.meta.dirname, "../../..");
const sources = ["packages/agent-ui/src", "packages/workspace/src", "apps/web/src", "apps/desktop/src"];
const forbidden = [
  "sqlite3", "SQLite", "SqliteDatabase",
  "RelationalConversationRepository", "RelationalMessageRepository", "RelationalDocumentRepository",
  "AVA_PERSISTENCE", "ava.infrastructure.persistence",
  "EventSource", "WebSocket",
  "deleteDocument", "@tiptap/",
];
function files(directory: string): string[] { return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => entry.isDirectory() ? files(join(directory, entry.name)) : entry.name.endsWith(".ts") || entry.name.endsWith(".tsx") ? [join(directory, entry.name)] : []); }

describe("Step 4.11/4.12 frontend boundaries", () => {
  it("keeps transport, persistence, editor, and scope details out of UI shells", () => {
    for (const directory of sources) for (const file of files(join(root, directory))) {
      if (file.endsWith("step411.architecture.test.ts")) continue;
      const text = readFileSync(file, "utf8");
      expect(text).not.toMatch(/fetch\s*\(\s*[`'"]\/?(?:conversations|messages|documents|attachments)(?:\/[\w/*-]*)?[`'"]/);
      for (const token of forbidden) expect(text).not.toContain(token);
    }
  });
  it("keeps web and desktop on the shared workspace composition", () => {
    for (const app of ["apps/web/src", "apps/desktop/src"]) {
      const text = files(join(root, app)).map((file) => readFileSync(file, "utf8")).join("\n");
      expect(text).toContain("@ava/workspace");
    }
  });
});
