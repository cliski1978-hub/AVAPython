/** AVA workspace discovery contract. */

import type { ContractVersion } from "./version";

export type WorkspaceKind = "local" | "ephemeral";

/** Safe public metadata for an AVA-approved workspace.
 *
 * Mirrors the backend ``WorkspaceInfo`` exactly: only identity (workspace id,
 * display name, kind). Host filesystem paths and internal security details
 * are never part of this contract.
 */
export interface WorkspaceInfo {
  workspace_id: string;
  display_name: string;
  kind: WorkspaceKind;
}

/** Response contract for the GET /workspaces endpoint. */
export interface WorkspaceDiscoveryResponse {
  contract_version: ContractVersion;
  workspaces: WorkspaceInfo[];
}