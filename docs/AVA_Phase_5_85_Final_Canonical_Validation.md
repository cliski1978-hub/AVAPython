# Phase 5.85 — Final Canonical Validation

**Status: COMPLETE**
**Release readiness: READY FOR PHASE 6**
**Schema: 18**

This is the final Phase 5 certification record. It closes validation and
documentation only; Phase 5.85 adds no production feature, API, UI, schema, or
migration. The only source changes in this phase update stale schema-version
expectations in tests so they describe the already-certified v18 migration
registry.

## Scope and authoritative phase inventory

The completed canonical sequence and its detailed records are:

| Phase | Completed scope | Record |
| --- | --- | --- |
| 5.1 | Provider/model/runtime architecture audit | [5.1](AVA_Phase_5_1_Provider_Model_Runtime_Architecture_Audit.md) |
| 5.2 | Provider connection domain | [5.2](AVA_Phase_5_2_Provider_Connection_Domain.md) |
| 5.3 | Provider connection persistence | [5.3](AVA_Phase_5_3_Provider_Connection_Persistence.md) |
| 5.4 | Model configuration domain | [5.4](AVA_Phase_5_4_Model_Configuration_Domain.md) |
| 5.5 | Model configuration persistence | [5.5](AVA_Phase_5_5_Model_Configuration_Persistence.md) |
| 5.6 | Runtime configuration domain | [5.6](AVA_Phase_5_6_Runtime_Configuration_Domain.md) |
| 5.7 | Runtime configuration persistence | [5.7](AVA_Phase_5_7_Runtime_Configuration_Persistence.md) |
| 5.8 | Application execution defaults | [5.8](AVA_Phase_5_8_Application_Execution_Defaults.md) |
| 5.9 | Credential reference strategy | [5.9](AVA_Phase_5_9_Credential_Reference_Strategy.md) |
| 5.10 | Settings API | [5.10](AVA_Phase_5_10_Settings_API.md) |
| 5.11 | Settings UI foundation | [5.11](AVA_Phase_5_11_Settings_UI_Foundation.md) |
| 5.12 | Provider connection management UI | [5.12](AVA_Phase_5_12_Provider_Connection_Management_UI.md) |
| 5.13 | Model management UI | [5.13](AVA_Phase_5_13_Model_Management_UI.md) |
| 5.14 | Runtime management UI | [5.14](AVA_Phase_5_14_Runtime_Management_UI.md) |
| 5.15 | Defaults UI | [5.15](AVA_Phase_5_15_Defaults_UI.md) |
| 5.16 | Execution configuration resolver | [5.16](AVA_Phase_5_16_Execution_Configuration_Resolver.md) |
| 5.17 | Configuration bootstrap/migration compatibility | [5.17](AVA_Phase_5_17_Configuration_Bootstrap_Migration_Compatibility.md) |
| 5.18 | Production conversation architecture audit | [5.18](AVA_Phase_5_18_Production_Conversation_Architecture_Audit.md) |
| 5.19 | Normalize Conversation/Run relationships | [5.19](AVA_Phase_5_19_Normalize_Conversation_Run_Relationships.md) |
| 5.20 | Message status normalization | [5.20](AVA_Phase_5_20_Message_Status_Normalization.md) |
| 5.21 | Context construction service | [5.21](AVA_Phase_5_21_Context_Construction_Service.md) |
| 5.22 | Context window management | [5.22](AVA_Phase_5_22_Context_Window_Management.md) |
| 5.23 | Run lifecycle normalization | [5.23](AVA_Phase_5_23_Run_Lifecycle_Normalization.md) |
| 5.24 | Durable run cancellation | [5.24](AVA_Phase_5_24_Durable_Run_Cancellation.md) |
| 5.25 | Streaming transport contract | [5.25](AVA_Phase_5_25_Streaming_Transport_Contract.md) |
| 5.26 | Persisted event sequence/replay | [5.26](AVA_Phase_5_26_Persisted_Event_Sequence_Replay.md) |
| 5.27 | Partial assistant response rendering | [5.27](AVA_Phase_5_27_Partial_Assistant_Response_Rendering.md) |
| 5.28 | Reconnect/resume | [5.28](AVA_Phase_5_28_Reconnect_Resume.md) |
| 5.29 | Run recovery after refresh | [5.29](AVA_Phase_5_29_Run_Recovery_After_Refresh.md) |
| 5.30 | Backend restart recovery semantics | [5.30](AVA_Phase_5_30_Backend_Restart_Recovery_Semantics.md) |
| 5.31 | Retry/regenerate across persisted runs | [5.31](AVA_Phase_5_31_Retry_Regenerate_Across_Persisted_Runs.md) |
| 5.32 | Stale event protection | [5.32](AVA_Phase_5_32_Stale_Event_Protection.md) |
| 5.33 | Conversation-level concurrency rules | [5.33](AVA_Phase_5_33_Conversation_Level_Concurrency_Rules.md) |
| 5.34 | Failure and error UX | [5.34](AVA_Phase_5_34_Failure_and_Error_UX.md) |
| 5.35 | Configuration failure integration | [5.35](AVA_Phase_5_35_Configuration_Failure_Integration.md) |
| 5.36 | Web acceptance | [5.36](AVA_Phase_5_36_Web_Acceptance.md) |
| 5.37 | Desktop acceptance | [5.37](AVA_Phase_5_37_Desktop_Acceptance.md) |
| 5.38 | Restart/durability integration test | [5.38](AVA_Phase_5_38_Restart_Durability_Integration_Test.md) |
| 5.39 | Race/concurrency hardening | [5.39](AVA_Phase_5_39_Race_Concurrency_Hardening.md) |
| 5.40 | Full validation | [5.40](AVA_Phase_5_40_Full_Validation.md) |
| 5.40A | Backend full-validation notes | [5.40A](AVA_Phase_5_40A_Backend_Full_Validation_Notes.md) |
| 5.40B | Frontend full-validation notes | [5.40B](AVA_Phase_5_40B_Frontend_Full_Validation_Notes.md) |
| 5.40C | Static architecture/build notes | [5.40C](AVA_Phase_5_40C_Static_Architecture_Builds_Notes.md) |
| 5.40D | Canonical harness notes | [5.40D](AVA_Phase_5_40D_Canonical_Validation_Harness_Notes.md) |

The repository's canonical numbered sequence moves from 5.40 to 5.42; no
standalone 5.41 specification or completion record exists. The subsequent
reopened P1 remediation is an unnumbered post-closure record and is linked from
the [Phase 5 complete documentation](AVA_Phase_5_Complete_Documentation.md).
The completed extension sequence is:

| Phase | Completed scope | Record |
| --- | --- | --- |
| 5.42 | Conversation organization metadata domain | [5.42](AVA_Phase_5_42_Conversation_Organization_Metadata_Domain.md) |
| 5.43 | Conversation organization metadata persistence | [5.43](AVA_Phase_5_43_Conversation_Organization_Metadata_Persistence.md) |
| 5.44 | Conversation pin/unpin write path | [5.44](AVA_Phase_5_44_Conversation_Pin_Unpin_Write_Path.md) |
| 5.45 | Conversation archive/restore write path | [5.45](AVA_Phase_5_45_Conversation_Archive_Restore_Write_Path.md) |
| 5.46 | Conversation hard-delete service | [5.46](AVA_Phase_5_46_Conversation_Hard_Delete_Service.md) |
| 5.47 | Public conversation DELETE API | [5.47](AVA_Phase_5_47_Conversation_Delete_API.md) |
| 5.48 | Conversation delete UI and navigation | [5.48](AVA_Phase_5_48_Conversation_Delete_UI.md) |
| 5.49 | Conversation rename UX audit | [5.49](AVA_Phase_5_49_Conversation_Rename_UX_Audit.md) |
| 5.50 | Conversation search backend and typed client | [5.50](AVA_Phase_5_50_Conversation_Search_Backend_Client.md) |
| 5.51 | Conversation search UI | [5.51](AVA_Phase_5_51_Conversation_Search_UI.md) |
| 5.52 | Conversation sorting | [5.52](AVA_Phase_5_52_Conversation_Sorting.md) |
| 5.53 | Conversation Folder domain | [5.53](AVA_Phase_5_53_Conversation_Folder_Domain.md) |
| 5.54 | Folder persistence and CRUD API | [5.54](AVA_Phase_5_54_Conversation_Folder_Persistence_CRUD.md) |
| 5.55 | Folder sidebar UX | [5.55](AVA_Phase_5_55_Conversation_Folder_Sidebar_UX.md) |
| 5.56 | Project domain | [5.56](AVA_Phase_5_56_Project_Domain.md) |
| 5.57 | Project persistence | [5.57](AVA_Phase_5_57_Project_Persistence.md) |
| 5.58 | Project CRUD service and public API | [5.58](AVA_Phase_5_58_Project_CRUD_Service_API.md) |
| 5.59 | Project list page and navigation | [5.59](AVA_Phase_5_59_Project_List_Page_Navigation.md) |
| 5.60 | Project detail/workspace shell | [5.60](AVA_Phase_5_60_Project_Detail_Workspace_Shell.md) |
| 5.61 | Conversation ↔ Project relationship | [5.61](AVA_Phase_5_61_Conversation_Project_Relationship.md) |
| 5.62 | Project conversation API and creation flow | [5.62](AVA_Phase_5_62_Project_Conversation_API.md) |
| 5.63 | Project conversation UI | [5.63](AVA_Phase_5_63_Project_Conversation_UI.md) |
| 5.64 | Project instruction persistence audit/contracts | [5.64](AVA_Phase_5_64_Project_Instructions_Persistence.md) |
| 5.65 | Project instructions UI | [5.65](AVA_Phase_5_65_Project_Instructions_UI.md) |
| 5.66 | CORE system prompt domain | [5.66](AVA_Phase_5_66_CORE_System_Prompt_Domain.md) |
| 5.67 | CORE prompt persistence and CRUD | [5.67](AVA_Phase_5_67_CORE_Prompt_Persistence_CRUD.md) |
| 5.67A | Project conversation loading stabilization | [5.67A](AVA_Phase_5_67A_Project_Conversation_Regression_Fix.md) |
| 5.68 | Scoped CORE prompt assignment | [5.68](AVA_Phase_5_68_Scoped_CORE_Prompt_Assignment.md) |
| 5.69 | System prompt selection UI | [5.69](AVA_Phase_5_69_System_Prompt_Selection_UI.md) |
| 5.70 | Effective prompt resolver | [5.70](AVA_Phase_5_70_Effective_Prompt_Resolver.md) |
| 5.71 | Execution context injection | [5.71](AVA_Phase_5_71_Execution_Context_Injection.md) |
| 5.71A | Execution validation and stabilization | [5.71A](AVA_Phase_5_71A_Execution_Validation_Stabilization.md) |
| 5.72 | Project execution defaults domain/persistence | [5.72](AVA_Phase_5_72_Project_Execution_Defaults.md) |
| 5.73 | Project execution default resolution | [5.73](AVA_Phase_5_73_Project_Execution_Default_Resolution.md) |
| 5.74 | Project execution defaults UI | [5.74](AVA_Phase_5_74_Project_Execution_Defaults_UI.md) |
| 5.75 | Project Files domain | [5.75](AVA_Phase_5_75_Project_Files_Domain.md) |
| 5.76 | Project Files persistence/API/client | [5.76](AVA_Phase_5_76_Project_Files_Persistence_API_Client.md) |
| 5.76A | Project Files validation/stabilization | [5.76A](AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md) |
| 5.77 | Project Files UI | [5.77](AVA_Phase_5_77_Project_Files_UI.md) |
| 5.78 | Future Knowledge/RAG boundary | [5.78](AVA_Phase_5_78_Future_Knowledge_RAG_Boundary.md) |
| 5.79 | Folder drag/drop and New Chat in Folder | [5.79](AVA_Phase_5_79_Folder_Drag_Drop_New_Chat.md) |
| 5.79A | Folder drag/drop validation | [5.79A](AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md) |
| 5.80 | Archive views and sidebar cleanup | [5.80](AVA_Phase_5_80_Archive_Views_Sidebar_Cleanup.md) |
| 5.81 | Cross-feature deletion/cleanup integration | [5.81](AVA_Phase_5_81_Cross_Feature_Deletion_Cleanup_Integration.md) |
| 5.82 | Restart/durability certification | [5.82](AVA_Phase_5_82_Restart_Durability_Certification.md) |
| 5.83 | Backward compatibility/migration certification | [5.83](AVA_Phase_5_83_Backward_Compatibility_Migration_Certification.md) |
| 5.83A | Shared loading/recovery stabilization | [5.83A](AVA_Phase_5_83A_Shared_Loading_Regression_Recovery.md) |
| 5.84 | Web + Desktop acceptance | [5.84](AVA_Phase_5_84_Web_Desktop_Acceptance_Pass.md) |
| 5.84A | Native Tauri acceptance closure | [5.84A](AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md) |
| 5.85 | Final canonical validation and documentation | This document |

All listed extension phases are complete. Phase 6 was not started.

## Architecture and ownership certification

The final architecture remains the shared Web/Desktop workspace over one typed
API client and backend-owned durable state. `RunService → AgentPort` remains the
execution boundary. These distinctions remain intact:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Provider ≠ Provider Connection
Model ≠ Inference Runtime
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

Runtime and model resolve independently through `Explicit Run Override →
Project Default → Application Default → Bootstrap Fallback`. Prompt context
remains `AVA Root System → Resolved CORE Prompts → Project Instructions →
Conversation History → Current User Message`.

Folder membership and Project membership are independent. Conversation
Attachments remain separate from Project Files. Project Files remain source
resources only: no Knowledge/RAG ingestion, embedding, vector index, retrieval,
or execution integration is implemented. `@dnd-kit/core` 6.3.1 and
`@dnd-kit/sortable` 10.0.0 remain the shared drag/drop foundation; the audited
Conversation/Folder surface has no parallel native HTML drag implementation.

Backend durable state remains authoritative and frontends remain projections.
Conversation, Folder, Project and CORE deletion tombstones are transient
anti-race state, not database records. Archive is reversible and preserves the
conversation graph and independent memberships; hard delete is permanent.
Restart reconstruction and retryable loading/error/empty states remain covered
by the durability and 5.83A regression suites.

The certified cleanup ownership remains: Conversation deletion removes owned
messages/runs/events/attachments and conversation-scoped CORE assignments;
Folder deletion removes the Folder and clears `folder_id` while preserving
Conversations, Project membership, and archive state; Project deletion removes
Project-owned instructions/defaults/Files/content and Project assignments while
preserving Conversations and Folder membership; CORE prompt deletion removes
all of its assignments; Project File deletion addresses opaque identity and its
content reference. Durable examples are Conversations/messages/runs/events,
Folders, Projects, archive/pin, instructions/defaults, CORE definitions and
assignments, and Project File metadata/content. Selection, drag, loading,
search, pending mutations, and deletion tombstones are transient.

## Schema and migration audit

The registered migrations are contiguous **v1–v18**. A read-only check of the
live development database found versions 1 through 18, no foreign-key violations,
and `PRAGMA integrity_check = ok`. The Phase 5.83 historical certification
passed its fresh and historical baselines through v18 (including v9, v14, v15,
v16, and v17). The canonical backend harness also passed migration coverage.

No 5.85 migration is expected or was added. No Phase 5.85 edit touched
migration source. The migration diff audit found migrations v0001–v0009 AST-
identical to the repository HEAD version; registry changes register v0010–v0018,
which are the documented Phase 5 additions. The transaction runner has only
formatting changes relative to HEAD. The repository had a large pre-existing
dirty worktree at the start of this phase, so HEAD comparison is not treated as
a Phase 5.83 commit boundary.

The final migration compatibility test mutation proof is recorded in 5.83:
adding a default to the v17 nullable Project preference caused the regression
to fail; the test mutation was reverted and the original certification passed.

## Validation results

| Area | Result |
| --- | --- |
| Canonical `./scripts/test_all.sh` | PASS; 2,521 backend tests collected, 2,515 passed and 6 skipped; frontend checks and Python client checks also completed; exit code 0. |
| Attachment restart/recovery boundary | PASS in the restored canonical run; `tests/test_attachment_restart_recovery.py` completed. |
| Previously stale migration assertions | 11 targeted failures identified as v17 expectations; after updating those schema ceilings, all 11 passed, including full restart/API behavior. |
| Phase 5 direct backend subset | 189 passed, 4 explicitly skipped. |
| Backend Ruff | PASS. |
| Backend mypy | PASS, 236 source files. |
| Frontend TypeScript/lint | PASS across workspace packages/apps via canonical lint checks. |
| `@ava/desktop` | 11 passed. |
| `@ava/agent-ui` | 294 passed. |
| `@ava/workspace` | 209 passed, 6 opt-in live integration tests skipped. |
| `@ava/api-client` | 112 passed. |
| `@ava/contracts` | 42 passed. |
| `@ava/document-core` | 70 passed. |
| `@ava/settings-core` | 209 passed. |
| Python client | 10 passed; Ruff and mypy passed (3 source files). |
| Web production build | PASS; existing large-chunk advisory only. |
| Desktop frontend build | PASS; existing large-chunk advisory only. |
| Native Tauri all-target build | PASS; release executable, DEB, RPM, and AppImage produced. No package was installed or published. |
| Web live smoke | PASS: Connected Chat, existing conversation list, Projects and existing Project, Documents and existing documents, Settings and provider data. |
| Native live smoke, restart, and built-artifact smoke | PASS in 5.84A using the actual X11 window and release executable, including Chat/Projects/Documents/Settings and durable reconstruction after restart. The 5.85 all-target rebuild passed. This phase's CUA tool exposed no native app/window surface, so the newly rebuilt binary was not relaunched and no new native UI interaction/restart is claimed. |
| Current DB | Schema 18; 11 conversations, 0 folders, 1 Project, 2 Documents; known `Test project`, `Test 1`, and `Test 2` remain. Foreign-key check empty; integrity `ok`. |

The sandbox control reproduced an environment boundary: a minimal FastAPI
TestClient timed out and loopback socket creation returned
`PermissionError: [Errno 1] Operation not permitted`. With approved local socket
access, the minimal TestClient returned HTTP 200, loopback bind succeeded, and
the canonical aggregate harness completed. No AVA product workaround was
appropriate or added.

Phase 5-specific regressions are included in the full backend/frontend runs:
Conversation create/load/search/run lifecycle, archive/restore/pin/delete,
Folder assignment and Ungrouped behavior, Project relationships/instructions/
defaults/Files, CORE assignment/resolution/injection/cleanup, restart durability,
migration compatibility, and loading recovery. The documented migration
mutation proof above demonstrates that the suite detects a broken invariant.

## Static and public-surface audit

- Dependency placement is scoped: dnd-kit is declared by `@ava/agent-ui`;
  Tauri CLI is declared by `@ava/desktop`. No Redux, Zustand, Jotai, MobX, or
  comparable frontend state store was added.
- No vector/RAG dependency was found in Phase 5 package manifests/lockfile, and
  AVA-owned public contracts do not import provider/runtime vendor types.
- FastAPI route inventory includes health/capabilities, Conversations/messages,
  runs/events, Folders, Projects/Project conversations/defaults/Files, CORE
  prompts/assignments/resolution, Documents, and settings/model/provider/runtime
  surfaces. Typed clients correspond to the shipped public APIs; no missing
  Phase 5 route was found that warrants adding an API.
- Web Vite retains its strict 5173 port behavior and refuses silent fallback to
  Desktop's 5174; Tauri's development URL remains 5174.
- Production TODO/FIXME/HACK scans found no Phase 5 blocker. Remaining
  placeholders are intentional onboarding/optimistic UI or future-scope
  boundaries. There is no temporary Phase 5 feature flag hiding shipped work.
- Six backend skips are explicit optional/adaptor-specific tests (CORE scope
  adapters and OpenHands live qualification). Six frontend workspace skips are
  opt-in live-backend integration tests. The native pointer drag and native
  Project File download were not claimed as live-verified; 5.84A documents the
  evidence gap, while shared drag/drop/package tests, Web acceptance, and
  API/shared Project Files coverage pass. These remain accepted evidence gaps,
  not BLOCKER or MAJOR defects.

## Delivered capabilities and deferred scope

Phase 5 now provides durable conversation organization and lifecycle; Folders;
Projects with conversation relationships and instructions; reusable scoped CORE
prompts; per-axis execution defaults and prompt resolution/injection; Project
Files; searchable/sortable Chat and Archive views; shared dnd-kit Folder
movement; recovery/retry behavior; migration-safe persistence; and shared Web,
Desktop, and native Tauri shells.

Explicitly deferred beyond Phase 5: actual Knowledge/RAG ingestion, embeddings,
vector storage and retrieval; the complete Document Platform; nested Folders;
manual conversation ordering; broad future drag/drop scenarios (including
sortable lists and kanban); and distributed/multi-worker run ownership. Existing
Documents functionality is Phase 5 scope and is not represented as completion
of Phase 6's Complete Document Platform.

Phase 6 may treat the shared Web/Desktop shell, conversation foundation,
backend persistence, Projects/Folders, prompt resolution, execution selection,
Project Files, schema v18, and loading/recovery patterns as stable entry
boundaries. This is a handoff boundary only; Phase 6 design or implementation is
not started here.

## Findings and release decision

| Severity | Count | Finding |
| --- | ---: | --- |
| BLOCKER | 0 | None. |
| MAJOR | 0 | None. |
| MINOR | 0 | No unresolved Phase 5 defect found. |
| COSMETIC / accepted evidence gap | 2 | Native pointer drag and native Project File download were not independently exercised in 5.84A; see above. |

The final worktree still contains the pre-existing Phase 5 changes; no reset,
clean, or unrelated overwrite was performed. `git diff --check` passes. Phase
5.85 changes no production files and no migration files.

**Phase 5.85 complete. Phase 5 complete. Phase 5 canonical validation complete.**
No Phase 5 BLOCKER or MAJOR defects remain. **AVA is ready to begin Phase 6.**
Phase 6 is not started.
