import { describe, expect, it, vi } from "vitest";
import {
  ApiClient,
  ApiError,
  createProject,
  createProjectConversation,
  uploadProjectFile,
  downloadProjectFile,
  deleteProjectFile,
  getProjectFile,
  listProjectFiles,
  deleteProject,
  getProject,
  getProjectExecutionDefaults,
  listProjects,
  listProjectConversations,
  setProjectArchived,
  updateProject,
  updateProjectExecutionDefaults,
} from "./index";

const project = {
  id: "p/1",
  name: "Engineering",
  description: null,
  instructions: "Future context only",
  is_archived: false,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  contract_version: "v1" as const,
};

const conversation = {
  conversation_id: "c-1",
  title: "Project chat",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  is_pinned: false,
  is_archived: false,
  folder_id: null,
  project_id: "p/1",
  contract_version: "v1" as const,
};

describe("Project API client", () => {
  it("uses multipart upload and typed metadata/download/delete routes for Project files", async () => {
    const file = {
      id: "file-1", project_id: "p/1", file_name: "設計仕様書.pdf", content_type: "application/pdf",
      size_bytes: 3, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
      contract_version: "v1" as const,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: "p/1", files: [file], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(file), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(file)))
      .mockResolvedValueOnce(new Response(new Blob([new Uint8Array([0, 255, 1])])))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    const blob = new Blob([new Uint8Array([0, 255, 1])], { type: "application/pdf" });

    await expect(listProjectFiles(client, "p/1")).resolves.toMatchObject({ files: [file] });
    await expect(uploadProjectFile(client, "p/1", blob, { fileName: file.file_name })).resolves.toEqual(file);
    await expect(getProjectFile(client, "p/1", "file-1")).resolves.toEqual(file);
    await expect(downloadProjectFile(client, "p/1", "file-1")).resolves.toBeInstanceOf(Blob);
    await expect(deleteProjectFile(client, "p/1", "file-1")).resolves.toBeUndefined();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/projects/p%2F1/files",
      "http://localhost:8000/projects/p%2F1/files",
      "http://localhost:8000/projects/p%2F1/files/file-1",
      "http://localhost:8000/projects/p%2F1/files/file-1/content",
      "http://localhost:8000/projects/p%2F1/files/file-1",
    ]);
    const form = fetchMock.mock.calls[1][1]?.body as FormData;
    expect(form.get("file_name")).toBe(file.file_name);
    expect(form.get("file")).toBeInstanceOf(Blob);
    expect(fetchMock.mock.calls[1][1]?.headers).not.toHaveProperty("Content-Type");
    expect(fetchMock.mock.calls[4][1]?.method).toBe("DELETE");
  });

  it("uses typed Project execution-default routes and preserves patch omission", async () => {
    const defaults = {
      project_id: "p/1",
      runtime_key: "native",
      model_id: "model-a",
      runtime_available: true,
      contract_version: "v1" as const,
    };
    const cleared = { ...defaults, runtime_key: null };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(defaults)))
      .mockResolvedValueOnce(new Response(JSON.stringify(cleared)));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await expect(getProjectExecutionDefaults(client, "p/1")).resolves.toEqual(defaults);
    await expect(updateProjectExecutionDefaults(client, "p/1", { runtime_key: null })).resolves.toEqual(cleared);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/projects/p%2F1/execution-defaults",
      "http://localhost:8000/projects/p%2F1/execution-defaults",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toEqual({ runtime_key: null });
  });

  it("round-trips Project instructions and preserves omitted versus null update fields", async () => {
    const text = "Use UTF-8 →\n\nRules:\n  - 日本語\n  - Keep spacing.";
    const withInstructions = { ...project, instructions: text };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(withInstructions), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(withInstructions)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ projects: [withInstructions], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(withInstructions)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...withInstructions, instructions: null })));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    await expect(createProject(client, { name: "Engineering", instructions: text })).resolves.toEqual(withInstructions);
    await expect(getProject(client, "p/1")).resolves.toEqual(withInstructions);
    await expect(listProjects(client)).resolves.toEqual({
      projects: [withInstructions],
      contract_version: "v1",
    });
    await expect(updateProject(client, "p/1", { name: "Engineering" })).resolves.toEqual(withInstructions);
    await expect(updateProject(client, "p/1", { name: "Engineering", instructions: null })).resolves.toEqual({
      ...withInstructions,
      instructions: null,
    });

    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ name: "Engineering", instructions: text });
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({ name: "Engineering" });
    expect(JSON.parse(fetchMock.mock.calls[4][1]?.body as string)).toEqual({ name: "Engineering", instructions: null });
  });

  it("supports typed Project CRUD and archive operations", async () => {
    const archived = { ...project, is_archived: true };
    const updated = { ...project, name: "Platform" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(project), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ projects: [project], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(project)))
      .mockResolvedValueOnce(new Response(JSON.stringify(updated)))
      .mockResolvedValueOnce(new Response(JSON.stringify(archived)))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    await expect(createProject(client, { name: "Engineering" })).resolves.toEqual(project);
    await expect(listProjects(client)).resolves.toEqual({ projects: [project], contract_version: "v1" });
    await expect(getProject(client, "p/1")).resolves.toEqual(project);
    await expect(updateProject(client, "p/1", { name: "Platform" })).resolves.toEqual(updated);
    await expect(setProjectArchived(client, "p/1", { is_archived: true })).resolves.toEqual(archived);
    await expect(deleteProject(client, "p/1")).resolves.toBeUndefined();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/projects",
      "http://localhost:8000/projects",
      "http://localhost:8000/projects/p%2F1",
      "http://localhost:8000/projects/p%2F1",
      "http://localhost:8000/projects/p%2F1/archive",
      "http://localhost:8000/projects/p%2F1",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method ?? "GET")).toEqual([
      "POST",
      "GET",
      "GET",
      "PATCH",
      "PATCH",
      "DELETE",
    ]);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ body: JSON.stringify({ name: "Engineering" }) });
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ body: JSON.stringify({ name: "Platform" }) });
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ body: JSON.stringify({ is_archived: true }) });
    expect(fetchMock.mock.calls[5][1]?.body).toBeUndefined();
  });

  it("opts into deleting Project conversations only when explicitly requested", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ deleted_conversation_ids: ["c-1"] }), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await deleteProject(client, "p/1");
    await expect(deleteProject(client, "p/1", { deleteConversations: true })).resolves.toEqual(["c-1"]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/projects/p%2F1",
      "http://localhost:8000/projects/p%2F1?delete_conversations=true",
    ]);
  });

  it("propagates typed API errors for not-found and validation responses", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error_code: "project_not_found" }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "name must not be blank" }), { status: 422 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    await expect(getProject(client, "missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      body: { error_code: "project_not_found" },
    } satisfies Partial<ApiError>);
    await expect(createProject(client, { name: " " })).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      body: { detail: "name must not be blank" },
    } satisfies Partial<ApiError>);
  });

  it("lists and creates Project conversations with shared conversation contracts", async () => {
    const list = { conversations: [conversation], contract_version: "v1" as const };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(list)))
      .mockResolvedValueOnce(new Response(JSON.stringify(conversation), { status: 201 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    await expect(listProjectConversations(client, "p/1")).resolves.toEqual(list);
    await expect(createProjectConversation(client, "p/1", { title: "Project chat" })).resolves.toEqual(conversation);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/projects/p%2F1/conversations");
    expect(fetchMock.mock.calls[0][1]?.method ?? "GET").toBe("GET");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ title: "Project chat" }),
    });
  });

  it("propagates missing Project errors for Project conversation calls", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error_code: "project_not_found" }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error_code: "project_not_found" }), { status: 404 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await expect(listProjectConversations(client, "missing")).rejects.toMatchObject({
      name: "ApiError", status: 404, body: { error_code: "project_not_found" },
    });
    await expect(createProjectConversation(client, "missing", { title: "No Project" })).rejects.toMatchObject({
      name: "ApiError", status: 404, body: { error_code: "project_not_found" },
    });
  });
});
