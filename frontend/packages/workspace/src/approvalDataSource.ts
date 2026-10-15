import { ApiError, decideApproval, listApprovals, type ApiClient } from "@ava/api-client";
import {
  ApprovalDataError,
  type ApprovalDataSource,
  type ApprovalDetail,
  type ApprovalHistoryItem,
  type ApprovalStatus,
} from "@ava/approvals-core";
import type { ApprovalReviewItem } from "@ava/contracts";

function mapItem(item: ApprovalReviewItem): ApprovalDetail {
  return {
    approvalId: item.approval_id,
    toolName: item.tool_id,
    requestedAction: "Review normalized tool request",
    safeSummary: item.safe_summary,
    run: { id: item.run_id, label: item.run_id },
    requestedAt: item.requested_at,
    expiresAt: item.expires_at,
    status: item.status as ApprovalStatus,
    workspaceLabel: item.workspace_label ?? undefined,
    decisionAvailability: item.can_decide ? "available" : "not_authorized",
    invocationLabel: item.invocation_id,
    targetDescription: "Operation arguments are withheld from this review view.",
    requestedCapabilities: [],
    risk: "medium",
    reason: item.safe_summary,
    policyWarnings: [],
    decisionAt: item.decision_at ?? undefined,
    decisionLabel: item.decision_label ?? undefined,
  };
}

function asHistory(item: ApprovalReviewItem): ApprovalHistoryItem {
  if (item.status === "pending") throw new Error("A pending approval cannot be returned as history.");
  return mapItem(item) as ApprovalHistoryItem;
}

function mapError(error: unknown): ApprovalDataError {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403 || error.status === 404) return new ApprovalDataError("unauthorized");
    if (error.status === 409) return new ApprovalDataError("conflict");
    if (error.status === 410) return new ApprovalDataError("expired");
    if (error.status === 503) return new ApprovalDataError("unavailable");
  }
  return new ApprovalDataError("rejected");
}

export function createApprovalDataSource(client: ApiClient): ApprovalDataSource {
  return {
    async load() {
      try {
        const queue = await listApprovals(client);
        return {
          pending: queue.pending.map(mapItem),
          history: queue.history.map(asHistory),
        };
      } catch (error) {
        throw mapError(error);
      }
    },
    async decide(approvalId, decision) {
      try {
        return asHistory(await decideApproval(client, approvalId, decision));
      } catch (error) {
        throw mapError(error);
      }
    },
  };
}
