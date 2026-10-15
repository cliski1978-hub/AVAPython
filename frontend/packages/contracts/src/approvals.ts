/** Authenticated, disclosure-safe Approval API projections. */
export type ApprovalStatus = "pending" | "approved" | "denied" | "expired" | "cancelled" | "invalidated";
export type ApprovalDecision = "approve" | "deny";

export interface ApprovalReviewItem {
  approval_id: string;
  run_id: string;
  invocation_id: string;
  tool_id: string;
  tool_version: string;
  status: ApprovalStatus;
  requested_at: string;
  expires_at: string;
  safe_summary: string;
  decision_at: string | null;
  decision_label: "Authenticated reviewer" | null;
  workspace_label: string | null;
  can_decide: boolean;
}

export interface ApprovalQueueResponse {
  pending: ApprovalReviewItem[];
  history: ApprovalReviewItem[];
  contract_version: "v1";
}
