/** Safe presentation projections supplied only by an authorized backend. */
export type ApprovalStatus = "pending" | "approved" | "denied" | "expired" | "cancelled" | "invalidated";
export type ApprovalRisk = "low" | "medium" | "high" | "destructive";
export type ApprovalDecision = "approve" | "deny";
export type ApprovalDecisionAvailability = "available" | "not_authorized" | "unavailable";

export interface ApprovalListItem {
  approvalId: string;
  toolName: string;
  requestedAction: string;
  safeSummary: string;
  run?: { id: string; label?: string };
  conversation?: { id: string; label?: string };
  requestedAt: string;
  expiresAt: string;
  status: ApprovalStatus;
  workspaceLabel?: string;
  decisionAvailability: ApprovalDecisionAvailability;
}

export interface ApprovalDetail extends ApprovalListItem {
  invocationLabel: string;
  targetDescription: string;
  requestedCapabilities: string[];
  risk: ApprovalRisk;
  reason: string;
  policyWarnings: string[];
}

export interface ApprovalHistoryItem extends ApprovalDetail {
  status: Exclude<ApprovalStatus, "pending">;
  decisionAt?: string;
  decisionLabel?: string;
}

export interface ApprovalQueueSnapshot {
  pending: ApprovalDetail[];
  history: ApprovalHistoryItem[];
}

/**
 * Future authorized adapter seam. Implementations must return already-scoped,
 * disclosure-safe records and server-derived decision availability.
 */
export interface ApprovalDataSource {
  load(): Promise<ApprovalQueueSnapshot>;
  decide(approvalId: string, decision: ApprovalDecision): Promise<ApprovalHistoryItem>;
}

export type ApprovalServiceFailure = "unauthorized" | "unavailable" | "conflict" | "expired" | "rejected";

export class ApprovalDataError extends Error {
  constructor(readonly kind: ApprovalServiceFailure) {
    super(kind);
    this.name = "ApprovalDataError";
  }
}
