// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConversationList } from "@ava/agent-ui";

describe("System Prompt scoped entry points", () => {
  it("opens the conversation scope without selecting the conversation", () => {
    const onOpen = vi.fn();
    const onSelect = vi.fn();
    render(<ConversationList
      conversations={[{ id: "chat-1", title: "Draft", messages: [] }]}
      activeConversationId={null}
      onNewChat={() => undefined}
      onSelect={onSelect}
      onOpenConversationSystemPrompts={onOpen}
    />);
    const actions = screen.getByRole("button", { name: "Conversation actions for Draft" });
    expect(actions.getAttribute("aria-haspopup")).toBe("menu");
    expect(actions.getAttribute("aria-expanded")).toBe("false");
    expect(actions.className).toContain("bg-transparent");
    expect(actions.className).toContain("h-8");
    expect(actions.querySelector("svg")?.getAttribute("class")).toContain("lucide-ellipsis");
    fireEvent.click(actions);
    expect(actions.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("menuitem", { name: "System Prompts" }));
    expect(onOpen).toHaveBeenCalledWith("chat-1", "Draft");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("opens the folder scope without selecting or moving a conversation", () => {
    const onOpen = vi.fn();
    const onSelect = vi.fn();
    const onMove = vi.fn();
    render(<ConversationList
      conversations={[]}
      activeConversationId={null}
      onNewChat={() => undefined}
      onSelect={onSelect}
      folders={[{ id: "folder-1", name: "Research", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" }]}
      onOpenFolderSystemPrompts={onOpen}
      onMoveConversation={onMove}
    />);
    const actions = screen.getByRole("button", { name: "Folder actions for Research" });
    expect(actions.getAttribute("aria-haspopup")).toBe("menu");
    expect(actions.getAttribute("aria-expanded")).toBe("false");
    expect(actions.className).toContain("bg-transparent");
    expect(actions.querySelector("svg")?.getAttribute("class")).toContain("lucide-ellipsis");
    fireEvent.click(actions);
    expect(actions.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("menuitem", { name: "System Prompts" }));
    expect(onOpen).toHaveBeenCalledWith("folder-1", "Research");
    expect(onSelect).not.toHaveBeenCalled();
    expect(onMove).not.toHaveBeenCalled();
  });
});
