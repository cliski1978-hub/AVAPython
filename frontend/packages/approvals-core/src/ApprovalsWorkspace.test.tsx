import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalDataError, type ApprovalDataSource, type ApprovalDetail, type ApprovalHistoryItem, type ApprovalQueueSnapshot } from "./contracts";
import { ApprovalsWorkspace } from "./ApprovalsWorkspace";

const pending: ApprovalDetail = {
  approvalId: "approval:test-1", toolName: "File Writer", requestedAction: "Write a project file",
  safeSummary: "Create summary.txt in the selected project", invocationLabel: "Invocation 1",
  targetDescription: "Selected project file summary.txt", requestedCapabilities: ["workspace.write"], risk: "high",
  reason: "The operation changes a file", policyWarnings: ["The file will be replaced if it exists."],
  run: { id: "run:1", label: "Run 1" }, conversation: { id: "conversation:1", label: "Project discussion" },
  requestedAt: "2026-10-13T13:00:00Z", expiresAt: "2099-10-13T13:15:00Z", status: "pending",
  workspaceLabel: "Authorized project", decisionAvailability: "available",
};
const history: ApprovalHistoryItem = { ...pending, status: "denied", decisionAt: "2026-10-13T13:05:00Z", decisionLabel: "Reviewer" };
const snapshot = { pending: [pending], history: [history] };
const source = (overrides: Partial<ApprovalDataSource> = {}): ApprovalDataSource => ({
  load: vi.fn().mockResolvedValue(snapshot),
  decide: vi.fn().mockResolvedValue({ ...pending, status: "approved", decisionAt: "2026-10-13T13:06:00Z" }),
  ...overrides,
});

describe("ApprovalsWorkspace", () => {
  afterEach(cleanup);

  it("shows explicit unavailable state and does not invent or persist records without an adapter", () => {
    render(<ApprovalsWorkspace />);
    expect(screen.getByText("Approval service unavailable")).toBeTruthy();
    expect(screen.getByText(/no approval records are stored in the browser/i)).toBeTruthy();
    expect(screen.queryByText(pending.approvalId)).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("renders pending details, safe association fields, expiration and policy warnings", async () => {
    const api = source();
    render(<ApprovalsWorkspace dataSource={api} />);
    expect((await screen.findAllByText("File Writer")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Authorized project").length).toBeGreaterThan(0);
    expect(screen.getByText(/Invocation 1/)).toBeTruthy();
    expect(screen.getByText("The file will be replaced if it exists.")).toBeTruthy();
    expect(screen.getByText(/^Expires /)).toBeTruthy();
  });

  it("keeps decision controls disabled without backend-confirmed authority", async () => {
    const data = { ...pending, decisionAvailability: "not_authorized" as const };
    const api = source({ load: vi.fn().mockResolvedValue({ pending: [data], history: [] }) });
    render(<ApprovalsWorkspace dataSource={api} />);
    expect(await screen.findByText(/not authorized to decide/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Deny" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.decide).not.toHaveBeenCalled();
  });

  it("shows history as terminal and distinct from actionable requests", async () => {
    render(<ApprovalsWorkspace dataSource={source()} />);
    await screen.findAllByText("File Writer");
    fireEvent.click(screen.getByRole("tab", { name: "Approval history" }));
    expect((await screen.findAllByText("Denied")).length).toBeGreaterThan(0);
    expect(screen.getByText("Decision by Reviewer")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("shows denial as an approval outcome rather than a failed tool run", async () => {
    const denied = { ...pending, status: "denied" as const, decisionAt: "2026-10-13T13:06:00Z" };
    const api = source({ decide: vi.fn().mockResolvedValue(denied) });
    render(<ApprovalsWorkspace dataSource={api} />);
    await screen.findAllByText("File Writer");
    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm denial" }));
    expect(await screen.findByText("Approval was denied by the backend.")).toBeTruthy();
    expect(screen.getAllByText("Denied").length).toBeGreaterThan(0);
    expect(screen.queryByText(/tool execution failed/i)).toBeNull();
  });

  it("confirms consequential approvals and reports success only after backend confirmation", async () => {
    const api = source();
    render(<ApprovalsWorkspace dataSource={api} />);
    await screen.findAllByText("File Writer");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("dialog", { name: "Confirm approval" })).toBeTruthy();
    expect(api.decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("Approval was confirmed by the backend.")).toBeTruthy();
    expect(api.decide).toHaveBeenCalledTimes(1);
    expect(api.decide).toHaveBeenCalledWith(pending.approvalId, "approve");
    expect(screen.getByRole("tab", { name: "Approval history" }).getAttribute("aria-selected")).toBe("true");
  });

  it("does not show success when the decision is rejected or expires", async () => {
    const api = source({ decide: vi.fn().mockRejectedValue(new ApprovalDataError("expired")) });
    render(<ApprovalsWorkspace dataSource={api} />);
    await screen.findAllByText("File Writer");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("This approval has expired and can no longer be decided.")).toBeTruthy();
    expect(screen.queryByText("Approval was confirmed by the backend.")).toBeNull();
  });

  it("keeps expired or malformed-expiry requests non-actionable", async () => {
    const expired = { ...pending, expiresAt: "2020-01-01T00:00:00Z" };
    const { unmount } = render(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockResolvedValue({ pending: [expired], history: [] }) })} />);
    expect(await screen.findByText(/has expired and is no longer actionable/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    unmount();
    const malformed = { ...pending, expiresAt: "not-a-date" };
    render(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockResolvedValue({ pending: [malformed], history: [] }) })} />);
    expect(await screen.findByText(/has expired and is no longer actionable/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("disables a pending request when its expiry time passes while the view is open", async () => {
    const expiresAt = new Date(Date.now() + 40).toISOString();
    const item = { ...pending, expiresAt };
    render(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockResolvedValue({ pending: [item], history: [] }) })} />);
    expect((await screen.findByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(false);
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    });
  });

  it("prevents duplicate submissions while a backend decision is pending", async () => {
    let resolveDecision!: (value: ApprovalHistoryItem) => void;
    const decide = vi.fn(() => new Promise<ApprovalHistoryItem>((resolve) => { resolveDecision = resolve; }));
    const api = source({ decide });
    render(<ApprovalsWorkspace dataSource={api} />);
    await screen.findAllByText("File Writer");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const confirm = await screen.findByRole("button", { name: "Confirm approval" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(decide).toHaveBeenCalledTimes(1);
    resolveDecision({ ...pending, status: "approved", decisionAt: "2026-10-13T13:06:00Z" });
    expect(await screen.findByText("Approval was confirmed by the backend.")).toBeTruthy();
  });

  it("presents unauthorized and empty states distinctly", async () => {
    const unauthorized = source({ load: vi.fn().mockRejectedValue(new ApprovalDataError("unauthorized")) });
    const { unmount } = render(<ApprovalsWorkspace dataSource={unauthorized} />);
    expect(await screen.findByText("You are not authorized to view these approvals.")).toBeTruthy();
    unmount();
    render(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockResolvedValue({ pending: [], history: [] }) })} />);
    expect(await screen.findByText("There are no pending approvals.")).toBeTruthy();
  });

  it("shows loading and generic service error states", async () => {
    let rejectLoad!: (error: Error) => void;
    const api = source({ load: vi.fn(() => new Promise<ApprovalQueueSnapshot>((_, reject) => { rejectLoad = reject; })) });
    const { rerender } = render(<ApprovalsWorkspace dataSource={api} />);
    expect(screen.getByRole("status").textContent).toMatch(/loading approvals/i);
    rejectLoad(new Error("private server detail"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("private server detail")).toBeNull();
    rerender(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockRejectedValue(new ApprovalDataError("unavailable")) })} />);
    expect(await screen.findByText("Approval service unavailable")).toBeTruthy();
  });

  it("labels invalidated history as terminal and uses responsive semantic theme classes", async () => {
    const invalidated: ApprovalHistoryItem = { ...pending, status: "invalidated", resolutionReason: "Eligibility changed" } as ApprovalHistoryItem;
    render(<ApprovalsWorkspace dataSource={source({ load: vi.fn().mockResolvedValue({ pending: [], history: [invalidated] }) })} />);
    fireEvent.click(screen.getByRole("tab", { name: "Approval history" }));
    expect((await screen.findAllByText("Invalidated")).length).toBeGreaterThan(0);
    expect(document.querySelector("main")?.className).toContain("bg-background");
    expect(document.querySelector("main")?.className).toContain("text-foreground");
    expect(document.querySelector("main")?.className).toContain("sm:p-6");
    expect(document.querySelector("main")?.innerHTML).not.toContain("#000");
  });

  it("does not render unauthorized fields or overwrite the newest queue with a stale response", async () => {
    let resolveOld: ((value: typeof snapshot) => void) | undefined;
    const oldSource = source({ load: vi.fn(() => new Promise<ApprovalQueueSnapshot>((resolve) => { resolveOld = resolve; })) });
    const currentItem = { ...pending, approvalId: "approval:current", toolName: "Current Tool", workspaceLabel: undefined, workspaceRoot: "workspace-secret-root", credentials: "token-secret" };
    const newSource = source({ load: vi.fn().mockResolvedValue({ pending: [currentItem], history: [] }) });
    const { rerender } = render(<ApprovalsWorkspace dataSource={oldSource} />);
    rerender(<ApprovalsWorkspace dataSource={newSource} />);
    expect((await screen.findAllByText("Current Tool")).length).toBeGreaterThan(0);
    resolveOld?.(snapshot);
    await waitFor(() => expect(screen.queryByText("File Writer")).toBeNull());
    expect(screen.queryByText("workspace-secret-root")).toBeNull();
    expect(screen.queryByText("token-secret")).toBeNull();
    expect(Array.from(document.querySelectorAll("main div")).some((element) => element.className.includes("lg:grid-cols-"))).toBe(true);
  });
});
