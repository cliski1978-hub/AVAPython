/** Authenticated approval review API operations. */

import type { ApprovalDecision, ApprovalQueueResponse, ApprovalReviewItem } from "@ava/contracts";
import type { ApiClient } from "./client";

const json = (body: unknown) => ({ body: JSON.stringify(body) });

export async function listApprovals(client: ApiClient): Promise<ApprovalQueueResponse> {
  return (await client.request("/approvals")).json() as Promise<ApprovalQueueResponse>;
}

export async function decideApproval(
  client: ApiClient,
  approvalId: string,
  decision: ApprovalDecision,
): Promise<ApprovalReviewItem> {
  return (await client.request(`/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: "POST",
    ...json({ decision }),
  })).json() as Promise<ApprovalReviewItem>;
}
