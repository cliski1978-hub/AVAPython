# Phase 5.83 — Backward Compatibility / Migration Certification

Phase 5.83 certifies the existing SQLite migration chain through schema version
18 against historical databases built from the production migration registry.
It adds migration-focused tests and this record only; it changes no production
schema, migration, API, or UI behavior. Phase 5.84 has not started.

## Migration authority and inventory

`ava_schema_migrations` is the schema-version authority. The current registry is
contiguous from 1 through 18. Each migration is applied by the transactional
runner; applying an already-current database returns no pending versions. The
initial migration creates the Step 4.6 baseline; later migrations append their
versioned tables, indexes, or nullable columns. There is no downgrade path.

| Version | Migration | Compatibility effect |
| ---: | --- | --- |
| 1 | Initial application persistence schema | Creates the original runs, run_events, conversations, messages, and documents tables. Step 4.6 databases are structurally verified and adopted. |
| 2 | Document revision history | Adds document revision history. |
| 3 | Attachment metadata | Adds generic attachment metadata and owner lookup; no blob bytes are stored here. |
| 4 | Provider connections | Adds provider connection metadata. |
| 5 | Model configurations | Adds configured model metadata. |
| 6 | Runtime configurations | Adds configured runtime metadata. |
| 7 | Application execution defaults | Adds the singleton application-default record table. |
| 8 | Durable conversation/run relationships | Adds nullable run-to-conversation/message identifiers and lookup indexes. |
| 9 | Durable run cancellation request | Adds a nullable cancellation timestamp; historical runs remain unrequested. |
| 10 | Conversation organization metadata | Adds pin/archive flags with false defaults and nullable `folder_id`. |
| 11 | Conversation folders | Adds Folder metadata and its name index. |
| 12 | Projects | Adds Project metadata, including nullable description/instructions. |
| 13 | Conversation Project relationship | Adds nullable `project_id`; legacy conversations remain outside Projects. |
| 14 | Conversation Project lookup index | Adds the Project conversation lookup index. |
| 15 | CORE prompt definitions | Adds prompt definitions; no assignment is inferred from existing prompt rows. |
| 16 | Scoped CORE prompt assignments | Adds explicit assignments, uniqueness indexes, scope/mode checks, and prompt-delete cascade. No assignment row means INHERIT. |
| 17 | Project execution defaults | Adds nullable runtime and model preferences. Existing Projects inherit by having both unset. Model references use `ON DELETE SET NULL`. |
| 18 | Project files | Adds Project-owned file metadata and an index. `content_ref` is an opaque reference, not file bytes; Project deletion cascades metadata. |

### Ownership and reference map relevant to migration safety

| Record | Ownership / reference behavior | Upgrade implication |
| --- | --- | --- |
| Conversations, messages, runs, run events | Conversation transcript and execution graph are represented in their existing tables. Several relationships are service-enforced identifiers rather than SQLite foreign keys. | Upgrade tests preserve representative IDs, timestamps, body text, and references without rebuilding or re-seeding the graph. |
| Conversation Folders | Folder rows are independent metadata; `conversations.folder_id` is nullable and is not a declared FK. | Legacy conversations gain a null Folder association. Existing associations remain exact. |
| Projects | Project rows are independent metadata; `conversations.project_id` is nullable and is not a declared FK. Project execution `default_model_id` does reference configured models and becomes null when its model is deleted. | Legacy conversations remain unassigned. Existing Project associations are preserved. New execution preferences are null unless explicitly set. |
| CORE prompts / assignments | Prompt definitions own assignments through `core_prompt_assignments.core_prompt_id`, with `ON DELETE CASCADE`. Scope identity is application-managed; uniqueness/check constraints validate assignment shape. | Existing prompt definitions do not fabricate assignments; existing assignment records survive later migrations. |
| Conversation attachments | `attachments` stores metadata and an opaque `storage_key`; ownership is generic (`owner_type`/`owner_id`) and has no FK/cascade. Physical content belongs to a separate content store and may be shared. | Migration does not delete or rewrite association metadata or blobs. Conversation deletion policy must check sharing independently. |
| Project Files | Each metadata row references one Project with `ON DELETE CASCADE`; `content_ref` is unique metadata and does not contain blob bytes. | Version 18 creates an empty metadata table and no physical content. It does not transform Conversation Attachments into Project Files. |

## Upgrade matrix and evidence

`backend/tests/test_phase_5_83_migration_certification.py` builds each
historical schema by running the real migration registry up to the baseline,
inserts representative rows using that baseline schema, closes the database,
and opens it through the current registry or normal relational repository
composition.

| Historical baseline | Covered compatibility boundary |
| ---: | --- |
| v9 | Pre-Folder/Project conversation graph. Existing conversation, message, run, run-event, and attachment metadata survives v10–v18. Pin/archive begin false; Folder and Project IDs remain null; no CORE assignments or Project Files are invented. |
| v14 | Existing Folder, Project, conversation membership, archive/pin state, and whitespace Project instructions remain readable through normal repository composition after v15–v18. |
| v15 | Existing CORE prompt values and timestamps survive assignment/default/file migrations; the new assignment table is empty (INHERIT). |
| v16 | A populated pre-default Project receives null runtime/model defaults under v17, then survives v18 without materializing application defaults. |
| v17 | An existing Project with null execution defaults survives v18 with its ID/timestamps/defaults intact; Project Files starts empty. |
| Fresh/current | Existing migration tests cover fresh v0→v18, current-schema idempotence, exact ordering, adoption of the v1 legacy baseline, and rejection of malformed/gapped/future histories. New composition test verifies migration metadata timestamps and durable conversation state remain unchanged on a second migration. |

The upgrade checks also run SQLite `integrity_check` and `foreign_key_check`.
The normal persistence composition can read the upgraded database and retains
the canonical Conversation fields and Project instructions. A successful
schema migration does not claim that every historical database has valid domain
content; the runner still validates known schema structure and fails closed on
unsupported metadata/history.

The v14 normal-composition test writes a new Conversation and Folder, moves an
existing Conversation, edits Project instructions/defaults, toggles pin/archive,
then disposes and reconstructs the relational repositories twice. The second
startup applies zero migrations and preserves both the migration metadata
timestamps and the semantic Conversation snapshot. A v15 prompt baseline also
runs the current relational CORE resolver: an enabled legacy definition with no
assignment remains ineffective, while disabled/category/text values are
preserved exactly. A 100-Conversation, 300-message, 10-Project, 10-Folder smoke
graph preserves IDs and counts through v15–v18, including duplicate display
names, archived/pinned flags, Unicode, and null/empty distinctions.

A separate v14 upgrade test exercises current ownership services after normal
bootstrap: create a Project File, hard-delete the migrated Conversation, delete
the file and its exact content ref, delete the CORE prompt and assignments,
delete the Folder and Project, then verify empty metadata and clean SQLite
integrity. This confirms old Project/Folder/Conversation rows can participate in
the current cleanup lifecycle without row recreation.

Existing migration tests additionally cover v0→v18, v1 Step 4.6 adoption,
v2→v3, v8→v18, v14→v15, populated v16→v17, transaction rollback after an
injected failure, deterministic ordering, out-of-order/missing versions,
malformed metadata, and a future-version database. The runner records each
successful version once in `ava_schema_migrations`; failure rolls back DDL and
the version record together. On current-version startup it validates the latest
migration's declared structure (currently Project Files table columns); it does
not repair an externally altered database or comprehensively reconstruct every
prior table. A missing non-latest table in a hand-edited current database is
corruption and may fail when its repository is used. Downgrade is unsupported;
the app fails clearly rather than operating on a schema newer than its registry.

## Validation and environment classification

The dedicated certification suite passes directly without a server:
`8 passed`. The combined migration, 5.82 restart, and 5.81 deletion-cleanup
regressions pass: `41 passed`. Backend Ruff and mypy pass (236 source files).
CORE assignment/domain/persistence/resolver, execution prompt context and
selection, Project defaults/persistence, Project File contracts, and Knowledge
domain suites pass: `91 passed, 4 skipped`. Existing conversation pin/archive
service memory/SQLite cases also pass before their HTTP cases encounter the
TestClient blocker described below.
The agent-ui, workspace, API-client, and contracts suites pass: 293, 206, 112,
and 42 tests respectively; workspace has 6 existing skips. Their TypeScript
checks pass. Web and Desktop builds pass.

The broader socket-dependent backend run stops at
`test_http_archive_restore_validation_not_found_and_unfiltered_list` after its
two memory/relational service cases pass. A minimal independent FastAPI
TestClient reproduction prints `before` then remains stuck until the 15-second
timeout. Loopback socket creation independently raises
`PermissionError: [Errno 1] Operation not permitted` in this sandbox.
`./scripts/test_all.sh` was attempted and reached
`tests/test_attachment_restart_recovery.py` after 8% of 2,520 collected backend
tests, then remained there until the 90-second timeout. These are environment
blockers; no product workaround was added. The full backend suite and Python
client checks after that point remain unverified.

The test-only mutation that added `DEFAULT 'legacy-default'` to migration 0017
failed as required: an existing v16 Project gained that non-null value instead
of null. The original migration source was restored and the unmutated dedicated
suite passed again. No migration history or production schema was changed.

## Constraints and limits

The destructive content-store cleanup rules are unchanged. Attachment ownership
is generic and may refer to a Conversation, Message, or Document; there is no
database FK proving exclusive ownership of the corresponding stored bytes.
Consequently migration certification makes no claim that an attachment blob is
safe to delete. Project File metadata has an explicit Project FK cascade, while
its bytes remain in the configured content store under opaque refs.

Folder and Conversation-to-Project associations are intentionally nullable,
service-managed references in the current schema. Project defaults do not
backfill from application defaults: null means inherit at resolution time.
CORE prompt definitions do not imply a global assignment: no assignment means
INHERIT. Archive remains a reversible conversation flag and migration does not
convert archive state into deletion.

No historical production database or user-owned database was opened or changed;
all seeded data is in disposable temporary SQLite files. No live server, public
DELETE route, or future phase was part of this certification. Mixed-version
deployments and database downgrade are outside this certification.
