import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { PromptComposer } from "@ava/agent-ui";

function PromptComposerHarness({ onSubmit = vi.fn(), onStop = vi.fn() }: {
  onSubmit?: (prompt: string) => void;
  onStop?: () => void;
}) {
  const [profile, setProfile] = useState("profile-a");
  const [runtime, setRuntime] = useState("runtime-a");
  const [model, setModel] = useState("model-a");
  const [workspace, setWorkspace] = useState("workspace-a");
  return (
    <PromptComposer
      executionSummary={model === "model-a" ? "Model A" : "Model B"}
      controls={(
        <>
          <label>Profile<select aria-label="Select execution profile" value={profile} onChange={(event) => setProfile(event.target.value)}><option value="profile-a">Profile A</option><option value="profile-b">Profile B</option></select></label>
          <label>Runtime<select aria-label="Select runtime" value={runtime} onChange={(event) => setRuntime(event.target.value)}><option value="runtime-a">Runtime A</option><option value="runtime-b">Runtime B</option></select></label>
          <label>Model<select aria-label="Select model" value={model} onChange={(event) => setModel(event.target.value)}><option value="model-a">Model A</option><option value="model-b">Model B</option></select></label>
          <label>Workspace<select aria-label="Select workspace" value={workspace} onChange={(event) => setWorkspace(event.target.value)}><option value="workspace-a">Workspace A</option><option value="workspace-b">Workspace B</option></select></label>
        </>
      )}
      onSubmit={onSubmit}
      onStop={onStop}
    />
  );
}

function openSettings() {
  fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));
}

describe("wide prompt composer execution settings", () => {
  it("reveals settings on demand and keeps the current draft when configuration changes", () => {
    render(<PromptComposerHarness />);

    const message = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(message, { target: { value: "keep this draft" } });
    expect(screen.queryByRole("dialog", { name: "Execution settings" })).toBeNull();
    expect(screen.queryByLabelText("Select model")).toBeNull();

    openSettings();
    const model = screen.getByLabelText("Select model") as HTMLSelectElement;
    expect(model.value).toBe("model-a");
    fireEvent.change(screen.getByLabelText("Select execution profile"), { target: { value: "profile-b" } });
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe("keep this draft");
    fireEvent.change(screen.getByLabelText("Select runtime"), { target: { value: "runtime-b" } });
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe("keep this draft");
    fireEvent.change(model, { target: { value: "model-b" } });
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe("keep this draft");
    fireEvent.change(screen.getByLabelText("Select workspace"), { target: { value: "workspace-b" } });

    expect(screen.getByRole("button", { name: "Execution settings: Model B" })).toBeTruthy();
    expect(screen.getAllByRole("combobox")).toHaveLength(4);
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe("keep this draft");
  });

  it("supports Enter/Escape configuration access and preserves send behavior", () => {
    const onSubmit = vi.fn();
    render(<PromptComposerHarness onSubmit={onSubmit} />);
    const message = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(message, { target: { value: "  send this  " } });
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));
    const model = screen.getByLabelText("Select model");
    fireEvent.keyDown(model, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Execution settings" })).toBeNull();

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("send this");
  });

  it("keeps Stop available during a run and sends the existing stop callback", () => {
    const onStop = vi.fn();
    const { rerender } = render(<PromptComposerHarness onStop={onStop} />);
    rerender(<PromptComposer value="draft" isRunning onSubmit={vi.fn()} onStop={onStop} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
  });

  it("keeps the submitted draft and shows an actionable inline error when run creation fails", async () => {
    const onSubmit = vi.fn(async () => {
      throw new Error("configuration rejected");
    });
    render(<PromptComposerHarness onSubmit={onSubmit} />);

    const message = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    fireEvent.change(message, { target: { value: "keep this prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(
      "Unable to start this run. Check the selected runtime and model configuration, then try again.",
    ));
    expect(message.value).toBe("keep this prompt");
    expect(onSubmit).toHaveBeenCalledWith("keep this prompt");
  });

});
