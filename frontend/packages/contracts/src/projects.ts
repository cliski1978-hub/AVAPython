import type { ContractVersion } from "./version";

/** Durable AVA workspace/context metadata, distinct from a conversation folder. */
export interface Project {
  id: string;
  name: string;
  description: string | null;
  instructions: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}

export interface ProjectListResponse {
  projects: Project[];
  contract_version: ContractVersion;
}

export interface CreateProjectRequest {
  name: string;
  description?: string | null;
  instructions?: string | null;
  contract_version?: ContractVersion;
}

export interface UpdateProjectRequest {
  name: string;
  description?: string | null;
  instructions?: string | null;
  contract_version?: ContractVersion;
}

export interface SetProjectArchivedRequest {
  is_archived: boolean;
  contract_version?: ContractVersion;
}

/** Independent references to AVA-owned runtime and model identities. */
export interface ProjectExecutionDefaults {
  project_id: string;
  runtime_key: string | null;
  model_id: string | null;
  runtime_available?: boolean | null;
  contract_version: ContractVersion;
}

/** Omitted keys preserve current values; explicit null clears that preference. */
export interface UpdateProjectExecutionDefaultsRequest {
  runtime_key?: string | null;
  model_id?: string | null;
  contract_version?: ContractVersion;
}
