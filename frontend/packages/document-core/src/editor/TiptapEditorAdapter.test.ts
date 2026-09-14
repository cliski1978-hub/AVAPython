// @vitest-environment jsdom
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";
import { htmlContent } from "../model";
import { createTiptapEditorAdapter } from "./TiptapEditorAdapter";

describe("Tiptap editor adapter", () => {
  it("converts AVA HTML content at the adapter boundary", () => {
    const editor = new Editor({ extensions: [StarterKit], content: "<p>Initial</p>" });
    const adapter = createTiptapEditorAdapter(editor);
    expect(adapter.getContent()).toEqual(htmlContent("<p>Initial</p>"));
    adapter.setContent(htmlContent("<p>Updated</p>"));
    expect(adapter.getContent()).toEqual(htmlContent("<p>Updated</p>"));
    editor.destroy();
  });
});
