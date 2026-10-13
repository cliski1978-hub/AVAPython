// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Archive, Search, Trash2 } from "lucide-react";

import { IconButton } from "./icon-button";

afterEach(cleanup);

describe("shared IconButton", () => {
  it("renders the supplied Lucide icon and a required accessible name", () => {
    render(<IconButton icon={Archive} label="Archive conversation" />);
    const button = screen.getByRole("button", { name: "Archive conversation" });
    expect(button.querySelector("svg")).toBeTruthy();
    expect(button.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(button.className).toContain("rounded-md");
    expect(button.className).toContain("size-9");
    expect(button.querySelector("svg")?.getAttribute("class")).toContain("size-[18px]");
  });

  it("shows its tooltip without relying on it for the accessible name", async () => {
    render(<IconButton icon={Search} label="Search conversations" />);
    const button = screen.getByRole("button", { name: "Search conversations" });
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip").textContent).toBe("Search conversations");
    expect(button.getAttribute("aria-label")).toBe("Search conversations");
  });

  it("forwards Button variants, compact sizing, and the intentional circle exception", () => {
    render(<>
      <IconButton icon={Search} label="Compact search" size="compact" variant="outline" />
      <IconButton icon={Archive} label="Circular send" shape="circle" variant="secondary" />
    </>);
    const compact = screen.getByRole("button", { name: "Compact search" });
    const circle = screen.getByRole("button", { name: "Circular send" });
    expect(compact.className).toContain("h-8");
    expect(compact.className).toContain("border-input");
    expect(compact.querySelector("svg")?.getAttribute("class")).toContain("size-4");
    expect(circle.className).toContain("rounded-full");
    expect(circle.className).toContain("bg-secondary");
  });

  it("keeps disabled actions inactive and preserves rounded geometry", () => {
    const onClick = vi.fn();
    render(<IconButton icon={Trash2} label="Delete item" disabled onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Delete item" });
    fireEvent.click(button);
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.className).toContain("rounded-md");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders dense row actions with transparent resting chrome and a full compact hit target", () => {
    render(<IconButton icon={Search} label="Conversation actions" size="compact" appearance="row-action" />);
    const button = screen.getByRole("button", { name: "Conversation actions" });
    for (const className of ["h-8", "w-8", "border-0", "bg-transparent", "text-muted-foreground", "shadow-none", "hover:bg-muted", "hover:text-foreground", "focus-visible:ring-2"]) {
      expect(button.className).toContain(className);
    }
    expect(button.className).toContain("rounded-md");
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip").textContent).toBe("Conversation actions");
  });
});
