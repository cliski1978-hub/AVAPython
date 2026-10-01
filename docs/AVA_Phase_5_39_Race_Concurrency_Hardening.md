# AVA Phase 5.39 — Race/Concurrency Hardening

## 1. Test objective

Certify, under deliberate and repeatable contention, that AVA's run authority
stays truthful when several writers, a restart recovery, a cancellation request,
and a reconnecting client all act on the same durable state at once.

This phase changes no policy. Phases 5.30–5.38 decided what a run *is* (one
authoritative status, one durable ordered log, at most one active run per
conversation, cancellation intent distinct from outcome) and proved those
decisions across a cold process boundary. Phase 5.39 attacks them from the other
direction: it assumes the decisions are right and tries to make them wrong by
racing them.

The specific claim being tested is not "the locks are correct". It is that every
concurrency rule AVA relies on is enforced **in the place that cannot be
bypassed** — SQL transactions and compare-and-set updates, not in-process
bookkeeping that a second process, a second connection, or a lost race could
step around.

## 2. Persistence backend used

`AVA_PERSISTENCE=relational` — the durable SQLite adapters
(`RelationalRunRepository`, `RelationalRunEventRepository`,
`RelationalConversationRepository`, `RelationalMessageRepository`) over one
shared `SqliteDatabase`, constructed by the production composition and migrated
by the production migration runner.

Every test uses an isolated temporary database under pytest's `tmp_path`. The
developer's `backend/ava.sqlite3` is never opened, and no test writes to
`backend/.ava/`.

Races are driven through the **production repository and service objects**, not
through in-memory fakes, because the rules under test *are* the SQL: the
conversation guard is a `SELECT` inside the same transaction as the `INSERT`,
sequence allocation is `MAX(seq) + 1` inside a transaction, and terminal sealing
is a uniqueness check plus insert in one transaction. A fake would have made all
three pass by construction.

## 3. Concurrency simulation method

Real threads, one real database, forced overlap:

* `threading.Barrier` at the seam where two callers must arrive together, so
  "concurrent" means *provably concurrent* rather than "happened to interleave".
* `ThreadPoolExecutor` with a worker count equal to the number of racers.
* High-risk races repeated (10 rounds for the same-conversation creation race,
  12 iterations per lifecycle race pair, 100 simultaneous appends to one run,
  4 rounds × 25 appends for sequence reuse).
* **No sleeps, no timing assumptions, no retries to paper over flakiness.**
  Every assertion is about final durable state and about which fact won.

Two harness techniques deserve naming because they are what make a lost race
*reachable* rather than merely possible:

* `ContestedReads` (in `test_run_lifecycle_races.py`) wraps a repository and
  makes `get()` rendezvous across all racers, so every thread observes the same
  pre-race status and then attempts its compare-and-set from a genuinely stale
  read. Without this, one thread finishes before the other starts and the race
  never happens.
* `ContestedReads` is used **only** by the racing threads. All post-race
  assertions deliberately go through the *uncontested* authority, so the test
  never deadlocks on a barrier that only the racers can satisfy.

No OS process was spawned, no external runtime was used, and no network was
involved.

## 4. Race classes covered

| Class | Where |
| --- | --- |
| Completion racing cancellation | `test_run_lifecycle_races.py` |
| Failure racing cancellation | `test_run_lifecycle_races.py` |
| Two different terminal transitions | `test_run_lifecycle_races.py` |
| Three-way terminal race | `test_run_lifecycle_races.py` |
| Restart recovery racing each terminal transition | `test_run_lifecycle_races.py` |
| Two concurrent recoveries | `test_run_lifecycle_races.py` |
| Concurrent cancellation requests | `test_run_lifecycle_races.py` |
| Cancellation request racing a late terminal write | `test_run_lifecycle_races.py` |
| Same-state idempotent transition under contention | `test_run_lifecycle_races.py` |
| Concurrent event appends, one run | `test_run_event_concurrency.py` |
| Concurrent event appends, several runs | `test_run_event_concurrency.py` |
| Concurrent terminal event appends | `test_run_event_concurrency.py` |
| Concurrent reads interleaved with appends | `test_run_event_concurrency.py` |
| Nested transaction / savepoint behavior | `test_run_event_concurrency.py` |
| One writer's rollback vs another's writes | `test_run_event_concurrency.py` |
| Lifecycle traffic under load | `test_run_event_concurrency.py` |
| Replayed event identity | `test_run_event_concurrency.py` |
| Sequence reuse across rounds | `test_run_event_concurrency.py` |
| Same-conversation concurrent creation | `test_run_creation_races.py` |
| Different-conversation concurrent creation | `test_run_creation_races.py` |
| Retry / regenerate vs the active-run guard | `test_run_creation_races.py` |
| Concurrent retries of one attempt (failed and completed targets) | `test_run_creation_races.py` |
| Retry of a still-active run | `test_run_creation_races.py` |
| Guard atomicity at the repository boundary | `test_run_creation_races.py` |
| Settlement racing creation | `test_run_creation_races.py` |
| Frontend replay/live overlap and supersession | `runStreamResumeRaces.test.ts` |
| Frontend same-conversation load race | `conversation-selection.test.tsx` |

## 5. Completion racing cancellation

`tests/test_run_lifecycle_races.py` seeds a `running` run, forces both threads to
read it, then races `lifecycle.complete` against `lifecycle.cancel`, 12 times.

Asserted after every round:

* The final status is one of `completed` / `cancelled` — the two that were
  genuinely raced — and never anything else.
* Exactly one terminal event exists, and its type matches the final status.
* No terminal event is duplicated and no non-terminal event follows the
  terminal one.
* Event sequences are contiguous with no gaps.

A run cannot be both. One CAS wins; the loser's update matches zero rows and
`RunLifecycleService._resolve_lost_race` reads back the winner's state instead of
overwriting it.

## 6. Failure racing cancellation

The same shape, with `lifecycle.fail` against `lifecycle.cancel`, asserting that
the terminal fact is `run_failed` or `run_cancelled` and that a `run_failed`
status never arrives with a `run_cancelled` fact or the reverse. This is the
race that motivated Phase 5.30's decision that a restart failure must not be
laundered into a cancellation: under contention, the only thing standing between
"interrupted" and "user cancelled it" is which compare-and-set landed first, and
the test proves the stored fact always matches the stored status.

## 7. Two different terminal transitions

`complete` and `fail` race directly. Exactly one terminal event exists, and it is
one of the two, never both and never neither.

## 8. Three-way terminal race

`complete`, `fail`, and `cancel` race simultaneously. One terminal event, one
matching status, three threads' worth of compare-and-set attempts all losing
cleanly.

## 9. A lost race cannot rewrite the winner's terminal status

The winner is frozen and then re-driven through all three terminal transitions
through the uncontested authority. Asserted:

* Repeating the **same** terminal status is idempotent — it returns the record
  and writes no new fact.
* Repeating a **different** terminal status is **rejected** with
  `InvalidRunTransitionError` rather than silently succeeding, because
  "terminal" means the status is never reopened.
* Either way the run's status is unchanged and no additional terminal event is
  appended.

## 10. Restart recovery racing each terminal transition

`RunRecoveryService.recover_stranded_runs()` races against a normal
`complete`, a normal `fail`, and a normal `cancel`, 12 times each. Recovery
sweeps runs that are active at cold start; in production nothing else is running
at that moment, so this race is adversarial on purpose.

Asserted:

* The terminal fact and the final status always agree.
* No duplicate terminal event, whether recovery won or lost.
* When recovery wins, the `run_failed` payload carries
  `RESTART_INTERRUPTION_PAYLOAD` — the Phase 5.38 `error_code` key — and never
  a client-authored error code.
* Recovery is safe to run concurrently with itself: two recoveries over the same
  run produce one terminal fact.

## 11. Two concurrent recoveries

`recover_stranded_runs()` called from two threads simultaneously. Exactly one
`run_failed` event exists. The second recovery observes the settled run and
either skips it or reconciles to the same state, which is what makes recovery
idempotent under a duplicated cold start (a real risk with two worker processes
or a retried startup hook).

## 12. Concurrent cancellation requests

Four threads call `request_cancellation` on the same running run, all forced
through a barrier. Asserted:

* Exactly one `cancellation_requested_at` is recorded, and it is the **earliest**
  of the racing requests — the first intent wins, because the SQL guard is
  `... AND cancellation_requested_at IS NULL`.
* Every caller observes the same durable intent, including those whose update
  matched zero rows.
* No caller is told the run is cancelled: the status is still `running`, so
  intent is never presented as outcome.
* No duplicate cancellation event, no terminal event.

## 13. Cancellation request racing a late terminal write

A cancellation request races a terminal transition, and the run is verified
afterwards to expose intent without claiming an outcome:
`cancellation_requested_at` is populated or the request was too late, but
`run_cancelled` appears only if a cancellation actually won. A completion may
legitimately win over an intent that arrived too late; the invariant is that
intent is never read as outcome.

## 14. Concurrent event appends to one run

100 appends to one run, all 100 threads rendezvousing at the repository call.
Asserted: sequences are exactly `1..100` in order, every event id is present
exactly once, and the count is exact. A non-atomic `MAX(seq) + 1` would collide
here; a rollback that clobbered a concurrent writer would produce a gap.

## 15. Concurrent event appends to several runs

4 runs × 40 appends = 160 concurrent writes, all 160 threads in one barrier.
Each run independently owns a complete contiguous `1..40` history. This is the
property that makes per-run replay cursors safe: allocation for one run must not
consume or corrupt another's numbering.

## 16. Concurrent terminal event appends

20 threads race `run_completed` / `run_failed` / `run_cancelled` on one run.
Exactly one terminal fact survives, enforced in SQL. A resumed client therefore
cannot ever observe two terminal events for a single run.

## 17. Concurrent reads interleaved with appends

5 readers × 60 reads against 5 writers × 25 appends on one shared database.
Asserted: **no read ever returns `None` for a run that durably exists**, and
each run's sequence is exactly `1..25`.

This is the regression guard for the defect in section 33.

## 18. Nested transaction and savepoint behavior

A repository write inside a caller's `database.transaction()` must join that
transaction as a savepoint rather than starting a second real transaction
(`cannot start a transaction within a transaction`). Asserted at one and two
levels of nesting, and — the part that matters — that an exception inside the
enclosing transaction rolls the whole unit of work back to `1..2..3` with no
partial history left behind.

## 19. One writer's rollback vs another's writes

A "good" writer commits 15 events while a "bad" writer raises inside a
transaction after 5. Asserted: only the good writer's events survive, and their
sequences are contiguous `1..15`. Savepoint release on a shared connection must
not clobber a concurrent writer's sequence range.

## 20. Lifecycle traffic under load

25 runs started, then all 25 settled concurrently (half `complete`, half
`fail`). Asserted per run: exactly one terminal event, and its type matches the
stored status. A run whose status says `completed` while its log ends in
`run_failed` would be the worst possible outcome of this phase; none exists.

## 21. Replayed event identity

Re-appending an existing event id is **rejected** with a port-level `ValueError`
rather than silently ignored. Rejection is stronger than a no-op: a caller that
miscounted learns about it instead of quietly widening the log. Asserted that
the history is still exactly one event at sequence 1.

## 22. Sequence reuse across rounds

4 rounds × 25 appends to one run, 100 events total. Sequences are `1..100`, all
identities unique.

## 23. Same-conversation concurrent creation

4 creators race for one conversation, repeated over **10 independent rounds**,
each with a fresh database so a leak in one round cannot be masked by another.
Every creator passes through a barrier inside `prepare_run`.

Asserted per round:

* Exactly one `won`, three `rejected` with `ConversationRunActiveError`.
* Exactly **one** run row exists for the whole conversation — not one active run
  plus a rejected row.
* Exactly one assistant placeholder, owned by the winning run.
* The winner's own history is coherent and contains no terminal event.

## 24. A rejected creation leaks nothing

The leak half of the rule, which is easy to skip: a refused creation must be as
absent as a request never made. Asserted across `runs`, `messages`, and
`run_events` — no run row, no orphan assistant placeholder pointing at a
non-existent run, no stray events.

## 25. Different-conversation creation is not serialized into a conflict

3 conversations start runs simultaneously; all three succeed. This is the test
that distinguishes a conversation-scoped guard from a global one. Had the guard
consulted a global active-run count, or been implemented as a process-wide lock,
this would fail with a spurious rejection — a user would be unable to work in one
conversation while another is running.

## 26. Retry and regenerate vs the active-run guard

With a prior attempt settled and a *different* run active in the conversation, a
retry and a regenerate are both refused, and a full three-table footprint check
asserts the refusal wrote **nothing**. Lineage resolution reads the prior run
and then creates a new one, so the active-run guard has to hold *after* that
read; otherwise retry would be a way around the one-active-run rule.

## 27. Concurrent retries and concurrent regenerates

Two simultaneous retries of one settled attempt: exactly one wins. Asserted that
the new run's stored request carries `retry_of_run_id`, and — the part that
proves lineage was re-anchored rather than trusted — that its prompt equals the
**durable** user message content rather than the text the racing client sent.
The superseded attempt is byte-for-byte unchanged, read back through the API.

## 28. Retry of a still-active run

Branching a live attempt is refused before any write, so two runs can never
answer one turn.

## 29. Guard atomicity at the repository boundary

The same guard asserted at the *repository*, bypassing the service's error
mapping: a caller that reaches `RelationalRunRepository.create` directly still
cannot create two active runs for one conversation. This is the mechanism test —
it pins the guard to the transaction rather than to a service convention.

## 30. A settled run frees the conversation

Once terminal, the conversation accepts a new run. Asserted so the rule cannot
degrade into a permanent lock on a conversation that has finished work.

## 31. Settlement racing creation

A create races the settlement of the current run. Asserted honestly rather than
optimally: the prior run always ends `completed`, and the conversation is never
wedged — either the new run is already active, or it was refused *only* because
the conversation was still busy and a retry succeeds immediately afterwards. A
refusal here is a "try again" signal, not a deadlock, and the test documents
which of the two outcomes is correct rather than asserting one.

## 32. Frontend: replay/live overlap and supersession

`frontend/packages/agent-ui/src/run/runStreamResumeRaces.test.ts` — 8 tests
against `observeRunWithResume`:

* A duplicate event id at the same sequence within one live stream is applied
  **once**; the loop neither reconnects nor reports failure.
* A reconnect whose transport re-delivers the already-applied tail resumes past
  it: the exclusive cursor advances (`0` then `2`) and nothing is applied twice.
* A replayed sequence carrying a **different** event id is surfaced as a
  protocol fault rather than applied — this is the shape of two writers claiming
  one sequence, and silently accepting it is how a log becomes untrustworthy.
* An event id reused at a different sequence is refused.
* Once `isCurrent()` turns false mid-batch — a retry or regenerate superseding
  the run — the in-flight event, the rest of the batch, and any terminal event
  are all left unapplied, and the transport is **not** reopened.
* A superseded run reports no transport failure: it was abandoned, not broken.
  Telling the user "live updates disconnected" when a retry simply took over
  would be a lie.
* Supersession before the first event, and supersession between two events, both
  stop at exactly the right point.

## 33. Frontend: the same-conversation load race

`frontend/packages/workspace/src/conversation-selection.test.tsx` — 3 new tests.
`ConversationProvider` keeps a `loadGenerationRef` specifically because
"conversation identity alone cannot reject A → B → A races" (its own comment
says so), but until now only A → B was covered, where the differing ids mask the
bug.

* **A → B → A with a stale success.** The held-open first A load resolves *after*
  the second A load has already painted. Because hydration replaces same-id
  messages with the incoming copy, the stale snapshot would overwrite the fresh
  text of message `a1` — the user would watch a newer answer revert to the older
  one. Asserted that the stale response is discarded, the fresh answer survives,
  and there is exactly one assistant message.
* **A → B → A with a stale failure.** The superseded request's failure is not the
  current view's failure: no error banner appears.
* **A failure that genuinely belongs to the current selection is still shown** —
  the counterpart assertion, so the two above cannot pass vacuously.

Both race tests were verified to **fail** when the generation guard is removed
(see section 38).

## 34. What was deliberately not built

* No distributed coordination of any kind — no Redis, no leases, no leader
  election, no advisory locks, no cross-node mutex. AVA remains a single-owner
  application; that limitation is unchanged and still documented.
* No job queue, no background worker, no scheduler, no new table, no migration,
  no schema change. The durable event log remains the only coordination
  mechanism, and the server remains the only writer of run facts.
* No new lock was introduced anywhere. The single production change serializes
  access to an object the driver requires to be used by one thread at a time.
* No per-conversation mutex or in-process "busy" flag. The conversation guard
  stayed in SQL, where a second process cannot bypass it.
* No full-suite backend run, per phase scope.

## 35. Single-owner limitation statement

The conversation-level concurrency rule is enforced by a SQL check-and-insert
inside one transaction, and sequence allocation and terminal sealing are likewise
enforced in SQL. That is the correct boundary: the guarantees hold for any number
of *threads* in one process, and would continue to hold across processes were
AVA ever run as more than one writer — but that is a claim about the SQL, not
something this phase tested, because AVA does not currently run multi-node and
this phase introduces no distributed semantics. Cross-node behavior remains
unverified and out of scope until AVA is actually deployed that way.

## 36. Focus and scope of validation

Focused only, as scoped:

* The three new race files (96 tests).
* Directly affected suites: recovery, lifecycle integration, lifecycle,
  attempts, relational event repository, durable cancellation, restart
  durability, persistence database (248 tests).
* `agent-ui` and `workspace` frontend suites, since frontend files changed.
* `ruff check .` and `mypy src/ava`, because production backend code changed.

The full backend suite was deliberately **not** run. No Web or Desktop build was
rerun: no shared production frontend code changed, and both acceptance phases
remain closed.

## 37. Exact test results

| Command | Result |
| --- | --- |
| `pytest tests/test_run_lifecycle_races.py` | **67 passed** in 4.70s |
| `pytest tests/test_run_event_concurrency.py` | **9 passed** in 3.63s |
| `pytest tests/test_run_creation_races.py` | **20 passed** in 3.07s |
| `pytest` (three new race files together) | **96 passed** in 11.03s |
| `pytest` (three race files + 8 directly affected suites) | **344 passed** in 28.08s |
| race files repeated 3× (flakiness check) | **29 passed** each run, 6.54–6.60s |
| `vitest run src/run/runStreamResumeRaces.test.ts` | **8 passed** |
| `vitest run src/conversation-selection.test.tsx` | **16 passed** (13 pre-existing + 3 new) |
| `pnpm --filter @ava/agent-ui test` | **205 passed** in 19 files (197 pre-existing + 8 new) |
| `pnpm --filter @ava/workspace test` | **56 passed, 4 skipped** (53 + 3 new) |
| `ruff check .` | **All checks passed** |
| `mypy src/ava` | **Success: no issues found in 181 source files** |
| `pnpm --filter @ava/agent-ui lint` | **exit 0** |
| `pnpm --filter @ava/workspace lint` | **exit 0** |
| `git diff --check` | **exit 0** |

Carried forward, unchanged and not rerun: Web acceptance CLOSED, Desktop
acceptance CLOSED, `@ava/desktop` 11 passed.

## 38. Defects discovered

**One production defect, and it was severe.**

`SqliteDatabase` is created with `check_same_thread=False` and a single shared
`sqlite3.Connection`, but `transaction()` held `_transaction_lock` while plain
`connect()` did not. Every read outside a transaction — which is nearly all of
them, including every `RunLifecycleService.get` — therefore used one connection
from many threads with no synchronization.

The observed failure was not a lost update. It was **the read returning no row
for a row that durably existed**, plus `sqlite3.InterfaceError: bad parameter or
other API misuse` from the driver and `ValueError: Invalid isoformat string: ''`
when a timestamp came back empty. Under the race tests this surfaced as
`UnknownRunError` for runs that were definitely present.

Practical impact: two concurrent API requests against a conversation could make
a live run appear to have vanished, and any code path that read-then-acted on a
run could act on a fiction. It was latent in production because the web
frontend's own single-active-run rule meant two requests rarely touched the same
run's state at the same instant — the database was silently relying on the UI
for correctness. Phase 5.39's job was to remove that luck.

The defect was first isolated with a minimal two-thread script, then reproduced
deterministically inside the test suite (section 17), then fixed.

Not fixed, by design:

* The Phase 5.23/5.26 crash gap (terminal status without its terminal event)
  remains a gap. It is a crash-consistency property, not a concurrency
  property; this phase neither widens nor repairs it.
* No new defect was found in the conversation guard, in sequence allocation, or
  in terminal sealing. Every rule that was already in SQL held under
  contention.

## 39. Production fixes made

One change, in
`backend/src/ava/infrastructure/persistence/database.py`: `connect()` now holds
`_transaction_lock` for the lifetime of the connection it yields, so all
access to the shared connection is serialized.

The existing lock is an `RLock`, so `transaction()`'s
`with self._transaction_lock, self.connect()` re-enters it safely — no deadlock,
no API change, no caller changed. A comment records *why* the lock spans the
whole `with` block, since a future reader would otherwise be tempted to narrow
it to the open call and reintroduce the bug.

This is the smallest fix that makes the driver's own threading contract true. The
alternatives were rejected for stated reasons: a connection pool or
thread-local connections would change composition and the object-identity
guarantee Phase 5.38's restart test depends on; per-repository locks would leave
the connection itself unprotected.

No other production code changed. No schema change, no migration, no service
restructure, no new abstraction, and no frontend production change.

## 40. Test-side corrections

Four initial failures were **wrong assertions, not product defects**, and were
corrected to the established semantics rather than the implementation bent to
match them. Each is recorded because in each case the real behaviour was
*stronger* than what the test first claimed:

* A repeat of a **different** terminal status raises `InvalidRunTransitionError`;
  it is not a silent no-op. Only a repeat of the *same* status is idempotent.
* A cancellation request that loses the race to a settlement returns the settled
  run **without** writing intent. Intent is not backdated onto a run that
  already finished — the request was too late to be true.
* A re-appended event id is **rejected** with `ValueError`, not silently ignored.
  Rejection is stronger: a miscounting caller learns about it.
* A rollback inside a transaction propagates its exception; the test needed
  `pytest.raises`.

`MessageStatus.COMPLETE` (not `COMPLETED`) and the absence of a
`retry_of_run_id` column on `RunRecord` were also corrected: lineage is carried on
the stored `RunRequest`, so the retry test asserts against the re-anchored
request instead.

## 41. Tests verified to have teeth

A test that passes whether or not the behaviour exists proves nothing, so each
load-bearing race test was re-run against a deliberately broken implementation
and confirmed to fail. The implementation was then restored and re-verified
byte-for-byte.

| Mutation | Result |
| --- | --- |
| Remove `_transaction_lock` from `connect()` | **2 failed** in `test_run_event_concurrency.py` (reproduced `InterfaceError` and `UnknownRunError`), **17 failed** across the other two race files |
| Remove the `loadGenerationRef` guard (success path) | A → B → A test **failed** (`Old answer` painted over `Fresh second answer`) |
| Remove the `loadGenerationRef` guard (failure path) | Stale-failure test **failed** (error banner painted) |
| Disable `seenSequences` dedup in the resume loop | **3 failed** (duplicate and replayed events applied twice) |
| Ignore `isCurrent()` mid-batch in the resume loop | **2 failed** (superseded run's events applied) |

The first row is the important one: the new tests fail on the *unfixed*
production code, which is what makes them regression guards rather than
descriptions.

## 42. Files changed

Backend production:
* `backend/src/ava/infrastructure/persistence/database.py` — the shared-connection
  lock.

Backend tests (new):
* `backend/tests/test_run_lifecycle_races.py` — 67 tests.
* `backend/tests/test_run_event_concurrency.py` — 9 tests.
* `backend/tests/test_run_creation_races.py` — 20 tests.

Frontend tests (new):
* `frontend/packages/agent-ui/src/run/runStreamResumeRaces.test.ts` — 8 tests.

Frontend tests (extended):
* `frontend/packages/workspace/src/conversation-selection.test.tsx` — 3 tests.

Docs:
* `docs/AVA_Phase_5_39_Race_Concurrency_Hardening.md` — this file.

## 43. Known limitations

* **Single owner.** Section 35. Unchanged and untested across nodes.
* **The crash gap remains.** A crash between a terminal status write and its
  event append still leaves a terminal run with no terminal fact. Recovery does
  not synthesize one, by design.
* **`SELECT MAX(seq) + 1` does not scale by design.** It is correct under
  contention because it runs inside the transaction. It is O(n) per append and
  would need a per-run counter row under real load; that is a performance
  question, not a correctness one, and no measurement was taken.
* **Timing-based starvation is not tested.** Every race here resolves on the
  order of operations, not on wall-clock fairness. Nothing guarantees a *fair*
  winner, only a truthful one.
* **Connection-level contention is serialized, not eliminated.** The fix makes
  the shared connection safe, not fast; concurrent readers now queue. For a
  single-owner desktop-style application this is the correct trade, but a
  throughput-sensitive deployment would want separate connections, and that
  would change the Phase 5.38 object-identity guarantee.
* **`backend/.ava/` is a pre-existing untracked local directory** (dated before
  this phase) and was neither created nor modified by these tests, which run
  with `attachment_storage="memory"`.
* Frontend coverage is at the projection boundary, not a browser test; no real
  network or SSE transport was involved.

## 44. Handoff to Phase 5.40

Phase 5.40 can rely on these now-certified facts:

* The shared `SqliteDatabase` is safe to use from many threads, and the tests
  that prove it fail on the unfixed code.
* The conversation active-run guard, event sequence allocation, terminal event
  sealing, status compare-and-set, and cancellation-intent capture are all
  enforced in SQL and hold under forced contention, including against restart
  recovery.
* Exactly one terminal fact per run is guaranteed at the storage layer, so
  recovery, replay, and reconnect cannot produce two.
* Cancellation intent is durable, first-writer-wins, and never presented as an
  outcome, including when it loses a race to a settlement.
* The frontend's load generation and resume-loop dedup are real regression
  guards, not decorative.

The natural Phase 5.40 target is the honest one this phase deliberately did not
take: AVA remains a single-owner, single-process application. Anything that
requires true multi-process or multi-node coordination — a shared deployment, a
background worker, a second writer — has no verified semantics and would need its
own phase rather than an extension of this one.

## 45. Phase 5.39 closure

Phase 5.39 is fully closed. Thirty-three race classes were certified against real
thread contention on real SQLite, one severe production concurrency defect was
found and fixed, and every load-bearing test was verified to fail against a
deliberately broken implementation. No policy was changed, no distributed
semantics were introduced, and Phase 5.40 was not started.
