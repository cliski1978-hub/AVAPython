# Phase 5.64 — Project Instructions Persistence Audit and Contract Completion

**Status: COMPLETE**

## Audit result

Project instructions were already persisted before this phase. The existing
canonical field is `ProjectRecord.instructions: str | None`; no separate
instruction entity or table is needed.

| Boundary | Result | Evidence |
| --- | --- | --- |
| Project record | COMPLETE | `ProjectRecord.instructions` is nullable text. |
| SQLite | COMPLETE | Migration 0012 created nullable `projects.instructions TEXT`; the repository writes, reads, and updates it. |
| Memory repository | COMPLETE | `ProjectStore` retains complete immutable Project snapshots. |
| Create contract/service/API | COMPLETE | Create accepts omitted, null, empty, or text values; only the Project name is normalized. |
| Update contract/service/API | COMPLETE | Pydantic's `model_fields_set` distinguishes omitted instructions from explicit null. The existing `PATCH /projects/{project_id}` is sufficient. |
| Response contract | COMPLETE | `ProjectResponse` exposes `instructions: str | None`; the route maps the canonical record field. |
| Typed client | COMPLETE | Existing create, update, get, and list methods serialize JSON bodies and return the response contract unchanged. |
| Frontend contract | COMPLETE | `Project.instructions` is `string | null`; write requests permit omission or null. |
| Execution use | NOT NEEDED | Repository-wide source search found no Project instruction read in run, context construction, or provider execution paths. |

The instructions section in `ProjectsWorkspace` remains the Phase 5.60
placeholder. The existing Project creation form can set initial instructions;
this phase adds no editing UI. Conversation records contain no instruction
field. Moving a Conversation updates only `project_id`; Project instructions
remain on their Project. Project deletion removes the Project row along with
its instructions and clears memberships through the existing relationship
cleanup.

## Canonical behavior

Project instructions are persistent Project-scoped text intended to influence
future conversation execution only after a later phase explicitly connects
them to run context. They remain inert data now. They are distinct from
system-wide instructions, model configuration, runtime configuration, and
agent-harness instructions. This phase defines no precedence, templates,
defaults, token budgeting, truncation, or prompt behavior.

Creation preserves the supplied value: omitted and explicit null both produce
`None`, empty text remains `""`, and non-empty text—including line breaks,
indentation, Markdown-like lists, code-like text, and Unicode—is stored
exactly. Updates preserve omitted instructions, clear them on explicit null,
and replace them exactly when given a string. JSON serialization preserves
these distinctions. No instruction-specific size limit exists in the current
contract; none was introduced.

Every metadata update advances `updated_at`, even if the supplied instruction
string equals the current value, because the existing generic Project update
service always advances that timestamp. Update preserves `id`, `created_at`,
and archive state; omitted description is also preserved. Archive and restore
use their existing idempotent operation, preserve instructions, and only
advance the timestamp when archive state changes.

## Persistence and validation

Migration 0012 already defines `instructions TEXT` without `NOT NULL`, so no
migration was added. Focused regression coverage verifies memory/SQLite
parity, direct `SELECT instructions` values for null, empty, multiline, and
Unicode text, service/API create and update behavior, omitted versus explicit
null, archive preservation, unrelated metadata, and SQLite close/reopen
durability for replacement and clearing. API-client coverage verifies create,
get, list, and update responses plus omitted/null/multiline request
serialization. Existing Project domain coverage confirms instructions are not
part of Conversation records. No full canonical suite was run.

The focused backend run passed 36 tests. Two unrelated stale assertions were
excluded after failing in the unfiltered run: one expects the pre-5.61
Conversation shape, and one expects schema version 13 although migration
0014 is present. The API-client package passed 105 tests and the contracts
package passed 33 tests. Ruff passed for the focused Project backend files,
mypy passed for all 204 backend source files, TypeScript checks passed for
the API-client and contracts packages, and `git diff --check` passed.

No production change was warranted: the Phase 5.57–5.58 behavior already met
the persistence contract. No production mutation was appropriate because
Phase 5.64 verified existing behavior without changing it. The changes in this
phase are focused regression tests and this audit record only.
