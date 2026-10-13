# Phase 5.82 — Restart / Durability Certification

Phase 5.82 certifies Phase 5 state across a cold application reconstruction.
It adds test and certification documentation only; it does not add product
behavior, migrations, or persistence changes.

## Durable, transient, and derived state

| State | Classification | Restart rule and evidence |
| --- | --- | --- |
| Conversation identity, title, timestamps, pin/archive flags, Folder ID, Project ID | DURABLE | SQLite conversation records are reopened by a fresh app composition. |
| Conversation messages and durable partial assistant content | DURABLE | Message records/content are reopened; partial output remains while its run is reconciled. |
| Run identity, lifecycle state, execution selection, relationships | DURABLE | Run records are reopened. Terminal runs remain terminal. |
| Run events and sequence fields | DURABLE | Existing events retain identity and order; startup recovery adds one terminal event only for stranded active runs. |
| Conversation attachment metadata/associations | DURABLE | Attachment metadata is in SQLite and association ownership is explicit. Conversation deletion cleans owned metadata. |
| Conversation attachment bytes | DURABLE when local storage is configured | They reopen from the configured attachment storage root; conversation deletion removes owned bytes. |
| Conversation Folder definitions and membership | DURABLE | Folder records and nullable Conversation folder IDs reconstruct from SQLite. |
| Project definitions, archive state, instructions, execution defaults | DURABLE | Project records reconstruct from SQLite, retaining null versus empty instructions and independently nullable default axes. |
| Conversation Project membership | DURABLE | The Conversation record is authoritative; Project deletion clears only this relationship. |
| Project File metadata and private content references | DURABLE | SQLite metadata retains opaque content references, which remain excluded from public responses. |
| Project File bytes | DURABLE when local storage is configured | Bytes reopen from the same configured Project File storage root and match exactly. |
| CORE prompt definitions and scoped assignments | DURABLE | Definitions and explicit assignment rows reconstruct; absent assignment remains INHERIT. |
| Configured providers, models, runtimes, and application execution defaults | DURABLE | Configuration repositories reconstruct after migrations and preserve stable AVA identities. Secrets are not included in snapshots. |
| Deleted Conversations, Folders, Projects, prompts, and Project Files | DURABLE absence | No tombstone is needed after reload; SQLite absence and cleanup are authoritative. |
| Active provider request / in-memory run observer | SESSION/TRANSIENT | A new process cannot resume the old in-flight request or observer. Startup recovery settles persisted active runs under the current single-process rule. |
| Frontend selected Conversation, selected Project, selected sidebar view, search query | SESSION/TRANSIENT | No localStorage, sessionStorage, or IndexedDB persistence was found in the audited frontend sources. Reload rebuilds view state from backend data. |
| Folder expanded/collapsed state, dnd-kit drag/overlay/drop state | SESSION/TRANSIENT | Component state resets; no active drag or pending drop is restored. |
| Pending mutations, pending requests, transient errors, deletion tombstones | SESSION/TRANSIENT | They are in-memory race/UI state. A reload gets canonical resources from the backend and naturally clears the old component state. |
| Composer draft | SESSION/TRANSIENT | No browser persistence was found; an unsent draft is not guaranteed to survive reload. |
| Active/Archived lists, Folder/Project groupings, sort order, transcript, search results | DERIVED | Recomputed from canonical backend records and existing ordering/projection rules. |
| Effective CORE prompt set/provenance and execution prompt layers | DERIVED | Recomputed from current definitions, assignments, canonical Conversation membership, Project instructions, and code-owned root prompt. |
| AVA root system prompt | DERIVED / APPLICATION-OWNED | Reconstructed from code; it is not persisted as user configuration. |

`DURABLE` means a fresh app/repository/service graph can read the same stored
meaning after reopening the same configured stores. `SESSION/TRANSIENT` is
process or page memory and is allowed to reset. `DERIVED` is recomputed from
durable state and application-owned rules rather than stored as an independent
truth.

## Certification topology

The new certification uses a unique `tmp_path` for each scenario:

```text
application A → file-backed SQLite + local attachment root + local Project File root
dispose all A resources
application B → same SQLite path + same configured roots
```

The tests use fresh `create_app` composition roots and enter the production
FastAPI lifespan, so B applies the normal migration/bootstrap path and startup
run recovery. API exercises use `httpx.ASGITransport`, which avoids the denied
loopback socket. A semantic pre-restart snapshot contains Projects, Folders,
Conversations and relationships, messages, run/event data, prompt definitions
and explicit assignments, global execution defaults, Project File metadata,
and content hashes. It intentionally excludes connection/service identity and
UI state. Neither test opens the user's configured database or content roots.

The disposable database reaches migration version 18. The main graph includes
P1/P2 plus P3 (null instruction state); F1/F2; the required four Conversation
shapes; pinned and archived state; four ordered transcript messages; a
completed run/event history; configured
provider/model/runtime identities; Project defaults (including one null axis);
null/non-empty/empty instruction values; enabled and disabled prompts plus a
prompt with no explicit assignment (INHERIT); global,
runtime, capability, Project, Folder, and Conversation assignments; and text,
binary, Unicode, distinct-name, and zero-byte Project Files.

## Restart behavior and results

The semantic snapshot is equal before and after a new application composition.
Conversation IDs, titles, ordering fields, pin/archive flags, Folder and Project
IDs, message IDs/order/content, terminal run identity/status, event IDs/order,
and sequence numbers survive. Search still matches durable titles. Active and
Archived source lists rebuild from Conversation flags; the frontend's active,
Folder, Project, and Archived views remain projections rather than a second
durable resource store.

CORE prompt resolution returns the same enabled/excluded records and winning
scope/provenance after restart. Execution prompt layers retain the same root,
resolved CORE prompts, and Project instruction text. Project default
preferences for a P1 Conversation are equivalent after restart. Prior
conversation history is available again to execution context construction.
An actual retry after reopening succeeds and inherits the persisted source-user
message identity from its terminal predecessor.
Global execution defaults preserve the configured provider-connection,
model, and runtime-configuration IDs; Project defaults preserve the runtime
key/model axes exactly and are not overwritten by fallback resolution.

Conversation-owned attachment metadata and bytes match the pre-restart
snapshot after reopening the configured attachment root. Project File metadata
and byte hashes match the pre-restart snapshot. Downloads
from the reopened local store match every original byte, including non-UTF-8
binary bytes and a zero-byte object. Unicode filenames round-trip exactly;
Project filenames remain unique within their owner while separate Projects
remain isolated. Public metadata omits
`content_ref`. The deletion case confirms hard deletion removes conversation
and message attachment associations and their local content. Project File
sibling content remains intact when a different Project File is deleted.

The partial-run scenario starts a run, persists partial assistant content, then
closes app A while the run is still active. On B's normal startup, the current
recovery rule marks it `failed` with `execution_interrupted`, retains the
partial content, preserves preexisting event records/sequences, and appends
one `run_failed` event. A further fresh composition does not append a duplicate
terminal event. This is recovery of durable state, not resumption of an active
provider request. AVA's current ownership assumption remains one process/worker;
in-flight local/provider work and in-memory run observers cannot survive a
process death.

Deletion/restart coverage confirms that a deleted Conversation and its
messages, run, events, conversation/message attachments, and scoped assignment
remain absent; deleted Folder membership is cleared while the Conversation's
Project survives; deleted Project membership is cleared while its Conversation
Folder survives; deleted prompt assignments do not return; and deleted
Project File metadata/bytes stay absent while an unrelated sibling remains.

The backend enables SQLite foreign keys; after restart the disposable
certification DB reports `PRAGMA foreign_key_check` with no rows and
`PRAGMA integrity_check` as `ok`. Migration version remains 18. A true abrupt
OS-process kill was not certified in this constrained environment; clean
application disposal/reconstruction and a durable active-run recovery scenario
were certified. SQLite WAL settings were not changed. Existing multi-resource
rollback and post-commit cleanup failure behavior remains covered by the
focused Project/Project File lifecycle tests; no cleanup worker or schema
change was introduced.

## Environment checks and validation

The canonical `./scripts/test_all.sh` was attempted. It reached
`backend/tests/test_attachment_restart_recovery.py` and stalled before
completing that file. The blocker was independently reproduced without AVA:

```text
bare FastAPI() + TestClient(...) + first GET: timed out after 12 seconds
127.0.0.1 socket bind: PermissionError: [Errno 1] Operation not permitted
```

This classifies the recurring attachment restart stall as a TestClient/AnyIO
environment lifecycle limitation, not an observed attachment content defect.
The new restart graph runs with ASGITransport and the focused attachment
content/restart evidence from earlier phases remains available, but the old
TestClient-based attachment restart test could not be re-certified in this
environment. A live browser check was attempted at `127.0.0.1:5174`; the
browser reported `ERR_CONNECTION_REFUSED`, so live reload and Desktop runtime
reload remain unverified here. Web and Desktop production builds do pass.

Validation outcomes for this phase:

- Phase 5.82 cold-restart graph, recovery idempotence, and deleted-resource
  reconstruction: 3 passed.
- Mutation proof: temporarily forcing SQLite `folder_id` reconstruction to
  `None` produced 1 failing restart test at the recovered C1→F1 assertion; the
  production adapter was restored and the certification suite passed again.
- Focused restart-safe domain/persistence regressions (Folders, Projects,
  Project Files, deletion cleanup, prompts, execution context/defaults, and
  sorting): 78 passed, 1 skipped.
- `backend/.venv/bin/mypy backend/src`: passed (236 source files).
- `backend/.venv/bin/ruff check backend/src backend/tests`: passed after fixing
  formatting/import issues in the new test.
- `pnpm --filter @ava/agent-ui --filter @ava/workspace --filter @ava/api-client
  --filter @ava/contracts test`: passed (653 passed, 6 skipped).
- The same four packages' TypeScript checks: passed.
- `pnpm --filter @ava/web build` and `pnpm --filter @ava/desktop build`: passed;
  Vite emitted its existing large-chunk advisory.
- `git diff --check`: passed.

The canonical harness and live browser validation remain blocked as stated
above. No production defect was reproduced, so this certification makes no
production-code or migration change.

## Completion

**Phase 5.82 complete. Restart and durability certification complete.**
The documented conclusions apply to clean application reconstruction over the
same configured SQLite and local content roots. They do not claim that active
provider requests resume after process death. No Phase 5.83 work was started.
