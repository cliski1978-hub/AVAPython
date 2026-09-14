import { describe, expect, it } from "vitest";
import { createAvaDocument, htmlContent } from "./index";

describe("AVA document model", () => {
  it("creates a clean serializable document with AVA-owned identity", () => {
    const document = createAvaDocument(htmlContent("<p>Hello</p>"), "2026-01-01T00:00:00.000Z");
    expect(document.id).toBeTruthy();
    expect(document.title).toBe("Untitled Document");
    expect(document.isDirty).toBe(false);
    expect(JSON.parse(JSON.stringify(document))).toEqual(document);
  });
});
