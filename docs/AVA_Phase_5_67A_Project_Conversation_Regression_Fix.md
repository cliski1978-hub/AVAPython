# Phase 5.67A — Project Conversation Load/Create Regression Fix

**Status:** Complete. The regression was caused by a stale backend process and
the live SQLite database still being at schema 12. The current application
already had the Project conversation routes and additive migrations; the
canonical backend was restarted against the existing live database so those
migrations could run without replacing user data.

## Live diagnosis

The failing Project was **Project 1**, ID
`2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480`, active, created and last updated at
`2026-10-02T11:33:37.507975Z`. The ID sent by the frontend was the durable
Project ID returned by `GET /projects`; it was not derived from the name,
index, or route placeholder.

The browser had been calling `http://127.0.0.1:8000`. The process occupying
that port was an older AVA server whose OpenAPI document did not register
either Project conversation route. Against it:

| Request | Result |
| --- | --- |
| `GET /projects/2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480` | `200`, Project 1 exists |
| `GET /projects/2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480/conversations` | `404`, `{"detail":"Not Found"}`, no application error code |
| `POST /projects/2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480/conversations` | `404`, `{"detail":"Not Found"}`, no application error code |

The first broken boundary was the active backend route table: the UI reached
an old server, before either request could reach `ConversationService`. The
live database was also behind the checked-in migration registry. It was at
schema 12, had a `projects` table, but had no `conversations.project_id`
column or `core_prompts` table. The Project relationship migration (13) could
not run while the stale process remained the owner of port 8000.

The only Project returned by the live `GET /projects` was Project 1. The UI's
`test` entry was a conversation Folder, not a second Project, so there was no
working Project 2 to compare. Project 1 was not archived. The live schema-12
database had ten conversations but no Project membership column, so their
historical Project ownership could not be inferred safely. No existing
conversation was deleted, recreated, or assigned speculatively.

## Repair and live result

The old process was stopped and the canonical `./scripts/dev_backend.sh`
launcher was started against the same `/tmp/ava-stabilization.sqlite3` file.
A read-only SQLite backup was taken first. Startup applied additive
migrations 13–15; the schema reached 15, `project_id` and `core_prompts` were
present, and Project 1 retained its original ID, name, description,
instructions, archive state, and timestamps. The repository `.env` was
restored after launch.

With the canonical process:

| Request | Result |
| --- | --- |
| `GET /projects/2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480/conversations` | `200`, valid empty `ConversationListResponse` before new Project chats |
| `POST /projects/2dc7b8e4-c849-4ff4-b733-3d7a6c4dc480/conversations` | `201`, created conversation `4478ea55-874a-4733-bd49-df6e91d8e45b` with the correct `project_id` |

The live browser then showed the legitimate empty state, created a chat in
Project 1, submitted “Reply with the single word ready.”, persisted both
messages, started a run, and displayed AVA's response, “Yes.” Project 1's
sidebar subsequently loaded that conversation without a refresh. The `test`
Folder remained separate and usable.

Global New Chat created a different conversation,
`028c8b79-9074-455e-9c66-43fbf9a8c222`, with `project_id = NULL`. A global
search for `New Conversation` returned the Project-scoped conversation in the
API results and displayed it under Project 1 in the sidebar. The existing
Project-move regression test continues to verify that assignment preserves
conversation identity, transcript, and Folder membership.

The live follow-up requested during validation also created the Folder
**Phase 5.67A test folder** (`c5b82eed-e31a-4018-970f-25a25bf01c8f`) and a
new conversation (`85f3eab8-1a00-48ac-971e-e91c571238a6`) inside it. Its
`project_id` is null and its `folder_id` points to that Folder.

## Regression coverage

Added a schema-12 startup/API regression that seeds an existing Project and
conversation, starts the current relational composition, and verifies that
startup upgrades the database, preserves the old records, serves the Project
list route, and creates a correctly scoped Project conversation.

Added workspace regressions for a failed Project conversation list followed
by a successful Retry, and a failed sidebar Project chat creation followed by
one successful retry. A search regression verifies that a Project-scoped
conversation appears in global search and opens through its canonical ID. A
focused Project-detail test also verifies its pending state clears after
failure. Updated an older migration assertion to include schema migration 15,
which was added by Phase 5.67.

Mutation proof disabled relational startup migration and ran the new
schema-12 regression: it failed with `sqlite3.OperationalError: no such column:
project_id` (one failed test). Restoring startup migration made the same test
pass.

Validation: the focused backend Project conversation, relationship, and
migration suites passed (45 tests); Ruff passed on the touched backend test
files; the focused workspace suite passed (147 tests, 6 skipped); the
API-client suite passed (107 tests); API-client, contracts, and workspace
TypeScript checks passed; Web and Desktop production builds passed; and
`git diff --check` passed. There were no backend production code changes, so
mypy was not required. No CORE prompt behavior changed. Phase 5.68 was not
started.
