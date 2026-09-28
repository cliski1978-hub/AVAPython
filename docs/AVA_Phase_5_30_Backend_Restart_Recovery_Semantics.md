# AVA Phase 5.30 — Backend Restart Recovery Semantics

## Status and audit

Before this phase, a durable `pending`, `running`, or `waiting_for_approval` run remained active across a backend restart. Native and OpenHands execution handles are in-memory task registries, so a fresh process owned none of those runs. Startup performed no active-run scan; SSE could tail an active snapshot indefinitely, and a post-restart cancellation could persist intent but could not prove an original task stopped. No code resumed execution.

## Policy

A stranded run is an active persisted run discovered at cold application startup, when its process-local execution owner is absent. Current AVA runtimes are process-local, so `pending`, `running`, and the presently writerless `waiting_for_approval` state all converge to `failed`. This is truthful: pending has no durable scheduler, running lost its task, and waiting has no durable continuation implementation. Cancellation intent is preserved but does not become cancellation, since acknowledgement was not observed.

The normalized recovery failure is:

```json
{"code":"execution_interrupted","message":"The backend restarted before this run completed."}
```

No provider, model, workspace, runtime, prompt, or assistant content is contacted or changed. Partial assistant `Message.content` remains exactly as written before loss.

## Ownership and persistence

`RunRecoveryService` is the backend application owner. During the FastAPI lifespan, before serving requests, it asks the shared `RunRepository.list_active()` boundary for deterministic `created_at, run_id` ordered snapshots and settles each through `RunLifecycleService.fail`. The lifecycle authority updates `updated_at`, preserves `created_at`, and appends one recovery-time `run_failed` fact with the next event sequence. Terminal runs are excluded and untouched, so repeated startup is idempotent.

The event is a new recovery-time fact, never fabricated history. Existing lifecycle/event crash-gap semantics remain: if status write succeeds but event append fails, a later startup sees the terminal run and does not synthesize a missing fact.

## Frontend and runtime boundary

After startup convergence, normal `GET /runs`, replay, SSE, and conversation status projection expose failed status. Phase 5.29 therefore renders durable partial content as failed and starts no active recovery observer; Phase 5.28 reconnect receives the terminal failure or reconciles its snapshot and stops. No frontend restart special case exists.

All current runtimes are assumed process-local. The service is runtime/provider-neutral and leaves room for a future external runtime survivability capability, without implementing remote execution recovery. AVA currently assumes one backend execution owner; multi-worker/distributed ownership leases are future work.

## Validation and handoff

Focused recovery/lifecycle/streaming coverage passed `90` tests. Full backend, frontend, TypeScript, builds, Ruff, mypy, and diff validation are recorded at closure. Phase 5.31 should add user-triggered retry/regenerate semantics for persisted terminal runs; it must not alter this startup truth-convergence policy.
