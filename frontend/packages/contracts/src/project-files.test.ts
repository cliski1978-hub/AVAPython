import { describe, expect, it } from "vitest";

import type { CreateProjectFileRequest, ProjectFile, ProjectFileListResponse } from "./index";
import { CONTRACT_VERSION } from "./version";

describe("Project file contracts", () => {
  it("mirrors the safe backend ProjectFileResponse fields", () => {
    const file: ProjectFile = {
      id: "file-1",
      project_id: "project-1",
      file_name: "résumé-日本語.pdf",
      content_type: "application/pdf",
      size_bytes: 0,
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
      contract_version: CONTRACT_VERSION,
    };

    expect(Object.keys(file).sort()).toEqual([
      "content_type",
      "contract_version",
      "created_at",
      "file_name",
      "id",
      "project_id",
      "size_bytes",
      "updated_at",
    ]);
    expect("content_ref" in file).toBe(false);
    expect("absolute_path" in file).toBe(false);
    expect(file.file_name).toBe("résumé-日本語.pdf");
    expect(file.size_bytes).toBe(0);
  });

  it("keeps the create metadata request separate from bytes and storage references", () => {
    const request: CreateProjectFileRequest = {
      file_name: "notes.md",
      content_type: "text/markdown",
      contract_version: CONTRACT_VERSION,
    };

    expect(Object.keys(request).sort()).toEqual(["content_type", "contract_version", "file_name"]);
    expect("content" in request).toBe(false);
    expect("content_ref" in request).toBe(false);
    expect("size_bytes" in request).toBe(false);
  });

  it("keeps Project file collections scoped to their owning Project", () => {
    const list: ProjectFileListResponse = {
      project_id: "project-1",
      files: [],
      contract_version: CONTRACT_VERSION,
    };

    expect(list.project_id).toBe("project-1");
    expect(list.files).toEqual([]);
  });
});
