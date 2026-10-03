import { describe, expect, it } from "vitest";
import type {
  CreateProjectRequest,
  Project,
  ProjectExecutionDefaults,
  UpdateProjectExecutionDefaultsRequest,
  UpdateProjectRequest,
} from "./projects";

describe("Project contracts", () => {
  it("models Project metadata independently from folders and execution defaults", () => {
    const project: Project = {
      id: "project-1",
      name: "Research",
      description: null,
      instructions: null,
      is_archived: false,
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:00:00Z",
      contract_version: "v1",
    };

    expect(Object.keys(project)).toEqual([
      "id",
      "name",
      "description",
      "instructions",
      "is_archived",
      "created_at",
      "updated_at",
      "contract_version",
    ]);
  });

  it("allows only the descriptive create/update fields", () => {
    const create: CreateProjectRequest = { name: "Research" };
    const update: UpdateProjectRequest = {
      name: "Research",
      description: "Background notes",
      instructions: "Use concise answers",
    };

    expect(create.name).toBe("Research");
    expect(update.description).toBe("Background notes");
  });

  it("keeps execution preferences independent and represents omitted versus clear", () => {
    const defaults: ProjectExecutionDefaults = {
      project_id: "p-1",
      runtime_key: "native",
      model_id: null,
      runtime_available: true,
      contract_version: "v1",
    };
    const preserve: UpdateProjectExecutionDefaultsRequest = {};
    const clearRuntime: UpdateProjectExecutionDefaultsRequest = { runtime_key: null };
    expect(defaults.model_id).toBeNull();
    expect(preserve).toEqual({});
    expect(clearRuntime).toEqual({ runtime_key: null });
  });
});
