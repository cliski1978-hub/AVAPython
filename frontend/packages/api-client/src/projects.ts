import type {
  ConversationListResponse,
  ConversationResponse,
  CreateConversationRequest,
  CreateProjectRequest,
  Project,
  ProjectExecutionDefaults,
  ProjectFile,
  ProjectFileListResponse,
  ProjectListResponse,
  SetProjectArchivedRequest,
  UpdateProjectRequest,
  UpdateProjectExecutionDefaultsRequest,
} from "@ava/contracts";
import { ApiClient } from "./client";

const path = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;

export async function listProjects(client: ApiClient): Promise<ProjectListResponse> {
  return (await client.request("/projects")).json();
}

export async function getProject(client: ApiClient, projectId: string): Promise<Project> {
  return (await client.request(path(projectId))).json();
}

export async function createProject(
  client: ApiClient,
  request: CreateProjectRequest,
): Promise<Project> {
  return (await client.request("/projects", { method: "POST", body: JSON.stringify(request) })).json();
}

export async function updateProject(
  client: ApiClient,
  projectId: string,
  request: UpdateProjectRequest,
): Promise<Project> {
  return (await client.request(path(projectId), { method: "PATCH", body: JSON.stringify(request) })).json();
}

export async function setProjectArchived(
  client: ApiClient,
  projectId: string,
  request: SetProjectArchivedRequest,
): Promise<Project> {
  return (await client.request(`${path(projectId)}/archive`, {
    method: "PATCH",
    body: JSON.stringify(request),
  })).json();
}

export async function deleteProject(client: ApiClient, projectId: string): Promise<void> {
  await client.request(path(projectId), { method: "DELETE" });
}

export async function getProjectExecutionDefaults(
  client: ApiClient,
  projectId: string,
): Promise<ProjectExecutionDefaults> {
  return (await client.request(`${path(projectId)}/execution-defaults`)).json();
}

export async function updateProjectExecutionDefaults(
  client: ApiClient,
  projectId: string,
  request: UpdateProjectExecutionDefaultsRequest,
): Promise<ProjectExecutionDefaults> {
  return (await client.request(`${path(projectId)}/execution-defaults`, {
    method: "PATCH",
    body: JSON.stringify(request),
  })).json();
}

export async function listProjectConversations(
  client: ApiClient,
  projectId: string,
): Promise<ConversationListResponse> {
  return (await client.request(`${path(projectId)}/conversations`)).json();
}

export async function createProjectConversation(
  client: ApiClient,
  projectId: string,
  request: CreateConversationRequest = {},
): Promise<ConversationResponse> {
  return (await client.request(`${path(projectId)}/conversations`, {
    method: "POST",
    body: JSON.stringify(request),
  })).json();
}

export async function listProjectFiles(
  client: ApiClient,
  projectId: string,
): Promise<ProjectFileListResponse> {
  return (await client.request(`${path(projectId)}/files`)).json();
}

export async function uploadProjectFile(
  client: ApiClient,
  projectId: string,
  file: Blob,
  options: { fileName: string; contentType?: string | null },
): Promise<ProjectFile> {
  const form = new FormData();
  form.append("file", file, options.fileName);
  form.append("file_name", options.fileName);
  if (options.contentType != null) form.append("content_type", options.contentType);
  return (await client.request(`${path(projectId)}/files`, { method: "POST", body: form })).json();
}

export async function getProjectFile(
  client: ApiClient,
  projectId: string,
  fileId: string,
): Promise<ProjectFile> {
  return (await client.request(`${path(projectId)}/files/${encodeURIComponent(fileId)}`)).json();
}

export async function downloadProjectFile(
  client: ApiClient,
  projectId: string,
  fileId: string,
): Promise<Blob> {
  return client.requestBlob(`${path(projectId)}/files/${encodeURIComponent(fileId)}/content`);
}

export async function deleteProjectFile(client: ApiClient, projectId: string, fileId: string): Promise<void> {
  await client.request(`${path(projectId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
}
