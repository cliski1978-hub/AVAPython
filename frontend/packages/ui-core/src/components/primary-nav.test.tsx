// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PrimaryNav } from "./PrimaryNav";

afterEach(cleanup);

describe("PrimaryNav", () => {
  it("renders all labeled destinations with Lucide icons and identifies the current route", () => {
    render(<PrimaryNav active="projects" onSelect={vi.fn()} />);

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav.querySelectorAll("svg")).toHaveLength(5);
    expect(nav.querySelector("ul")?.className).toContain("list-none");
    expect(screen.getByRole("link", { name: "Chat" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Documents" }).getAttribute("href")).toBe("/documents");
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings");
    expect(screen.getByRole("link", { name: "Approvals" }).getAttribute("href")).toBe("/approvals");
    expect(screen.getByRole("link", { name: "Settings" }).className).toContain("focus-visible:ring-2");
    expect(screen.getByRole("link", { name: "Settings" }).className).toContain("no-underline");
  });

  it("uses native link keyboard activation and calls the in-app selection handler", () => {
    const onSelect = vi.fn();
    render(<PrimaryNav active="chat" onSelect={onSelect} />);
    const projects = screen.getByRole("link", { name: "Projects" });

    projects.focus();
    expect(document.activeElement).toBe(projects);
    fireEvent.click(projects);
    expect(onSelect).toHaveBeenCalledWith("projects");
  });
});
