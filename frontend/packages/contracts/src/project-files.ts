import type { ContractVersion } from "./version";

/** Public metadata for one Project-owned file; content bytes and storage refs are internal. */
export interface ProjectFile {
  id: string;
  project_id: string;
  file_name: string;
  content_type: string | null;
  size_bytes: number;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}

/** Metadata accompanying a future upload transport; this contract carries no bytes. */
export interface CreateProjectFileRequest {
  file_name: string;
  content_type?: string | null;
  contract_version?: ContractVersion;
}

/** Project-scoped ordered collection of file metadata. */
export interface ProjectFileListResponse {
  project_id: string;
  files: ProjectFile[];
  contract_version: ContractVersion;
}
