import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const panelSource = readFileSync(join(import.meta.dirname, "ProjectFilesPanel.tsx"), "utf8");
const apiSource = readFileSync(join(import.meta.dirname, "../../../api-client/src/projects.ts"), "utf8");
const contractSource = readFileSync(join(import.meta.dirname, "../../../contracts/src/project-files.ts"), "utf8");

describe("Project Files UI boundaries", () => {
  it("uses typed Project File lifecycle methods and no raw transport", () => {
    for (const method of [
      "listProjectFiles",
      "uploadProjectFile",
      "downloadProjectFile",
      "deleteProjectFile",
    ]) {
      expect(panelSource).toContain(method);
      expect(apiSource).toContain(`export async function ${method}`);
    }
    expect(panelSource).not.toMatch(/\bfetch\s*\(/);
    expect(panelSource).not.toMatch(/\/projects\/\$\{/);
  });

  it("keeps storage references and execution/knowledge controls out of the public UI", () => {
    expect(contractSource).not.toMatch(/content_ref|storage_root|storage_path/);
    expect(panelSource).not.toMatch(/content_ref|storage_root|storage_path/);
    expect(panelSource).not.toMatch(/@ava\/(agent-ui|settings-core)/);
    expect(panelSource).not.toMatch(/Attach to chat|Send to conversation|Use in AI|Include in context|Index file|Embeddings|Knowledge status/);
  });
});
