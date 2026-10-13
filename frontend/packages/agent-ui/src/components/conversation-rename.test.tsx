// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { useState, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "../types";
import { ConversationList } from "./ConversationList";

(globalThis as unknown as Record<string, boolean>).IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => undefined;

function conversation(id: string, title: string): Conversation {
  return { id, title, messages: [] };
}

function render(element: ReactElement) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(element);
  });
  return {
    container,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true }),
    );
  });
}

const valueSetter = Object.getOwnPropertyDescriptor(
  globalThis.HTMLInputElement.prototype,
  "value",
)!.set;

function type(element: Element, value: string) {
  act(() => {
    valueSetter!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function pressKey(element: Element | Document, key: string) {
  act(() => {
    element.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });
}

function actionsButton(title: string): Element | null {
  return document.querySelector(`[aria-label="Conversation actions for ${title}"]`);
}

function renameInput(): HTMLInputElement | null {
  return document.querySelector('[data-conversation-renaming] input');
}

function menuItem(): Element | null {
  return document.querySelector('[data-conversation-rename]');
}

function deleteMenuItem(): Element | null {
  return document.querySelector('[data-conversation-delete]');
}

function rowSelectButton(id: string): Element | null {
  return document.querySelector(`[data-conversation-item="${id}"]`);
}

function errorStrip(): Element | null {
  return document.querySelector('[data-conversation-error]');
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ConversationList rename actions", () => {
  it("exposes an action/overflow control on a conversation item", () => {
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={async () => undefined}
        error={null}
      />,
    );
    expect(actionsButton("Old Title")).not.toBeNull();
  });

  it("keeps the ellipsis visible while its action menu is open", () => {
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId={null}
        onNewChat={noop}
        onSelect={noop}
        onRename={async () => undefined}
      />,
    );

    const actions = actionsButton("Old Title");
    expect(actions?.parentElement?.className).toContain("opacity-0");
    click(actions!);

    expect(menuItem()).not.toBeNull();
    expect(actionsButton("Old Title")?.parentElement?.className).toContain("opacity-100");
  });

  it("hides the action control when no rename handler is wired", () => {
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
      />,
    );
    expect(actionsButton("Old Title")).toBeNull();
  });

  it("opens a menu with a Rename action that exposes the current title as editable text", () => {
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={async () => undefined}
        error={null}
      />,
    );
    click(actionsButton("Old Title")!);
    const item = menuItem();
    expect(item).not.toBeNull();
    expect(item!.textContent).toBe("Rename");

    click(item!);
    const input = renameInput();
    expect(input).not.toBeNull();
    expect(input!.value).toBe("Old Title");
  });

  it("calls the backend-updating rename handler and renders the authoritative title", async () => {
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
    async () => undefined,
  );

    function Harness() {
      const [title, setTitle] = useState("Old Title");
      return (
        <ConversationList
          conversations={[conversation("c1", title)]}
          activeConversationId="c1"
          onNewChat={noop}
          onSelect={noop}
          onRename={async (id, title) => {
            await onRename(id, title);
            setTitle("Backend Title");
          }}
          error={null}
        />
      );
    }

    const { container } = render(<Harness />);
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "New Title");
    pressKey(input, "Enter");
    await flush();

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith("c1", "New Title");
    expect(container.textContent).toContain("Backend Title");
    expect(renameInput()).toBeNull();
  });

  it("confirms the rename on Enter", async () => {
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
    async () => undefined,
  );
    function Harness() {
      const [title, setTitle] = useState("Old Title");
      return (
        <ConversationList
          conversations={[conversation("c1", title)]}
          activeConversationId="c1"
          onNewChat={noop}
          onSelect={noop}
          onRename={async (id, title) => {
            await onRename(id, title);
            setTitle(title);
          }}
          error={null}
        />
      );
    }
    const { container } = render(<Harness />);
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "  New Title  ");
    pressKey(input, "Enter");
    await flush();

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith("c1", "New Title");
    expect(container.textContent).toContain("New Title");
  });

  it("guards duplicate Enter submissions while a rename request is pending", async () => {
    let resolveRename!: () => void;
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
      () => new Promise<void>((resolve) => { resolveRename = resolve; }),
    );
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={onRename}
      />,
    );
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "New Title");
    pressKey(input, "Enter");
    pressKey(input, "Enter");

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(renameInput()?.disabled).toBe(true);
    await act(async () => resolveRename());
    await flush();
    expect(renameInput()).toBeNull();
  });

  it("cancels the rename on Escape without calling the backend", () => {
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
    async () => undefined,
  );
    const { container } = render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={onRename}
        error={null}
      />,
    );
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "Discarded Title");
    pressKey(input, "Escape");

    expect(onRename).not.toHaveBeenCalled();
    expect(renameInput()).toBeNull();
    expect(container.textContent).toContain("Old Title");
  });

  it("rejects blank or whitespace-only titles without persisting", () => {
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
    async () => undefined,
  );
    const { container } = render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={onRename}
        error={null}
      />,
    );
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "   ");
    pressKey(input, "Enter");

    expect(onRename).not.toHaveBeenCalled();
    expect(renameInput()).toBeNull();
    expect(container.textContent).toContain("Old Title");
  });

  it("requires confirmation before delete and cancel/Escape never calls the delete handler", async () => {
    const onDelete = vi.fn<(_id: string) => Promise<void>>(async () => undefined);
    render(
      <ConversationList
        conversations={[conversation("c1", "Architecture Review")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onDelete={onDelete}
      />,
    );
    click(actionsButton("Architecture Review")!);
    expect(deleteMenuItem()?.textContent).toBe("Delete");
    click(deleteMenuItem()!);
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Delete “Architecture Review” permanently?');
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("cannot be undone");
    pressKey(document, "Escape");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("calls the delete handler only after the destructive confirmation", async () => {
    const onDelete = vi.fn<(_id: string) => Promise<void>>(async () => undefined);
    render(
      <ConversationList
        conversations={[conversation("c1", "Architecture Review")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onDelete={onDelete}
      />,
    );
    click(actionsButton("Architecture Review")!);
    click(deleteMenuItem()!);
    expect(onDelete).not.toHaveBeenCalled();
    const confirm = Array.from(document.querySelectorAll('[role="dialog"] button')).find((button) => button.textContent === "Delete permanently");
    click(confirm!);
    await flush();
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith("c1");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("does not select the conversation when opening the menu or choosing Rename", () => {
    const onSelect = vi.fn();
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={onSelect}
        onRename={async () => undefined}
        error={null}
      />,
    );
    click(actionsButton("Old Title")!);
    expect(onSelect).not.toHaveBeenCalled();
    click(menuItem()!);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("keeps the prior authoritative title and surfaces an error when the rename fails", async () => {
    const onRename = vi.fn<(_id: string, _title: string) => Promise<void>>(
      async () => {
        throw new Error("backend down");
      },
    );
    function Harness() {
      const [title, setTitle] = useState("Old Title");
      return (
        <ConversationList
          conversations={[conversation("c1", title)]}
          activeConversationId="c1"
          onNewChat={noop}
          onSelect={noop}
          onRename={async (id, title) => {
            await onRename(id, title);
            setTitle(title);
          }}
          error="Unable to rename conversation."
        />
      );
    }
    const { container } = render(<Harness />);
    click(actionsButton("Old Title")!);
    click(menuItem()!);
    const input = renameInput()!;
    type(input, "New Title");
    pressKey(input, "Enter");
    await flush();

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Old Title");
    expect(container.textContent).not.toContain("New Title");
    expect(errorStrip()).not.toBeNull();
    expect(errorStrip()!.textContent).toBe("Unable to rename conversation.");
  });

  it("still selects the conversation when the row itself is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ConversationList
        conversations={[conversation("c1", "Old Title")]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={onSelect}
        onRename={async () => undefined}
        error={null}
      />,
    );
    click(rowSelectButton("c1")!);
    expect(onSelect).toHaveBeenCalledWith("c1");
  });

  it("keeps at most one conversation in rename mode at a time", () => {
    render(
      <ConversationList
        conversations={[
          conversation("c1", "First"),
          conversation("c2", "Second"),
        ]}
        activeConversationId="c1"
        onNewChat={noop}
        onSelect={noop}
        onRename={async () => undefined}
        error={null}
      />,
    );
    click(actionsButton("First")!);
    click(menuItem()!);
    expect(renameInput()).not.toBeNull();

    click(actionsButton("Second")!);
    click(menuItem()!);
    expect(renameInput()).not.toBeNull();
    expect(renameInput()!.value).toBe("Second");
    expect(document.querySelectorAll('[data-conversation-renaming]')).toHaveLength(1);
  });
});
