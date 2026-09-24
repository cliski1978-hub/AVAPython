# AVA Phase 3 — Handoff for the Next Agent

Prepared: 2026-09-14. Latest completed work: **Step 16 — Runtime Resolver**.

## Start here

Phase 3 is complete through the individually supplied Step 16 prompt. The real
local-model execution path works, and the separate runtime port, implementation,
registry, and resolver now exist and are tested. **The runtime stack is not wired
into production.** No Step 17 work has begun.

The latest full test and build gates passed. This handoff is documentation only;
no code was changed after the Step 16 validation.

Read these next:

1. [Implementation log](AVA_Phase_3_Implementation_Log.md) — authoritative record
   of actual completed behavior, tests, caveats, and per-step files.
2. [Architecture audit](AVA_Phase_3_Architecture_Audit.md) — read the Step 13–16
   clarifications at the top before the historical Sprint 2 baseline.
3. [Local development](Local%20Development.md) — includes optional live-model
   validation instructions.
4. The user's next step prompt. Do not infer authorization to implement the
   remaining roadmap from this handoff.

## Important roadmap discrepancy

The original [Phase 3 plan](AVA_Phase_3_Model_and_Agent_Runtime_Abstraction.md)
labels Step 16 “Add Runtime Configuration and Resolver” and Step 17 “Record
Runtime and Model in Run Metadata.” However, the user's actual Step 16 prompt
explicitly limited implementation to the resolver and prohibited runtime
configuration, production composition, and agent migration.

Therefore, **configuration/composition are still missing deliberately**, despite
what the older roadmap title suggests. Do not assume they were implemented or
skip that gap. Follow the next explicit user prompt. If it assumes production
runtime selection already works, explain this discrepancy before making dependent
changes. Earlier audit proposals to inject models/runtimes into RunService are
also obsolete; the top-of-file clarifications and actual code supersede them.

## Working tree and source-control status

- Repository branch at handoff: `master`.
- Latest commit: `7b6c736` — Sprint 2 core AI user experience.
- **The Phase 3 work is uncommitted**, spanning many modified and untracked files.
  This includes the entire runtime package, multiple model/provider files, tests,
  and the implementation log.
- Preserve this working tree. Do not reset, clean, overwrite, or treat untracked
  files as disposable. A diff against HEAD includes accumulated Phase 3 work,
  not merely Step 16.
- No commit, PR, or deployment was created during these steps.
- Run `git status --short` before beginning and distinguish your new changes
  from the existing work.

## Completed work

| Stage | Actual state |
| --- | --- |
| Initial audit | Historical baseline and architecture review documents exist. |
| Steps 2–7 | Model/runtime metadata contracts, hardened model port, model registry, model configuration, and model resolver implemented. |
| Step 8 plus 8A/8B | OpenAI-compatible HTTP provider, error/lifecycle corrections, transport configuration validation. |
| Step 9 | Local provider constructed and registered through infrastructure composition; lifespan owns provider shutdown. |
| Step 10 | Model-provider discovery API, service, and client/contracts support. |
| Step 11 | NativeAgentAdapter executes through an injected ModelProviderPort; failure/cancellation normalization and offline tests. |
| Step 12 | Real Ollama vertical slice passed through AVA HTTP API, including success, retrieval, and real connection-failure handling. |
| Step 13 | AgentRuntimePort and independent RuntimeRunResult added. |
| Step 14 | NativeRuntime implemented and tested, but not used by the application. |
| Step 15 | Pure RuntimeRegistry added, but not instantiated by production composition. |
| Step 16 | Pure RuntimeResolver and UnknownRuntimeError added, but not instantiated by production composition. |

## Current production architecture

```text
POST /runs
  → RunService
  → AgentPort
  → NativeAgentAdapter                 when AVA_AGENT_PROVIDER=native
  → injected ModelProviderPort
  → OpenAICompatibleModelProvider
  → Ollama /v1/chat/completions
```

The default agent remains **mock**. Mock runs do not resolve a model provider,
so `agent_provider=mock` with an unknown model provider remains startable.
Native composition resolves the configured model provider explicitly; an unknown
provider fails composition rather than falling back.

`create_app()` composes the model registry/resolver once, then constructs the
agent through infrastructure composition. Discovery uses that same model
registry, and native execution receives the same registered provider instance.
Startup performs no health/generation network call. Discovery invokes provider
health; run execution invokes generation. Provider shutdown remains lifespan/
composition-owned.

**RunService knows only AgentPort, not model or runtime selection.** It owns AVA
run IDs, state, and event normalization. Stores remain in memory.

## Runtime stack available for future composition

Relevant files under `backend/src/ava/`:

| File | Responsibility |
| --- | --- |
| `contracts/runtimes.py` | Canonical RuntimeInfo and RuntimeCapabilities. |
| `runtimes/contracts.py` | AgentRuntimePort and internal RuntimeRunResult. |
| `runtimes/adapters/native/native_runtime.py` | NativeRuntime implementation. |
| `runtimes/registry.py` | Pure runtime-instance storage. |
| `runtimes/resolver.py` | Exact runtime ID lookup and UnknownRuntimeError. |
| `runtimes/__init__.py` | Exports port, result, registry, resolver, and error. |

```python
class AgentRuntimePort(ABC):
    def get_runtime_info(self) -> RuntimeInfo: ...
    async def execute(
        self, *, run_id: str, request: RunRequest,
        model_provider: ModelProviderPort,
    ) -> RuntimeRunResult: ...
    async def cancel_run(self, run_id: str) -> RuntimeRunResult: ...

class RuntimeRunResult(BaseModel):
    status: RunStatus
    content: str | None = None
```

The three port methods are abstract. **Runtime selection and model-provider
selection are independent axes.** ModelProviderPort is supplied at execution
time; NativeRuntime's constructor receives no provider. Future composition may
resolve both axes separately, then pass the selected provider to execute.
Neither resolver chooses the other axis.

### NativeRuntime behavior

- Identity: `native`; display name: `AVA Native Runtime`.
- All ten RuntimeCapabilities flags remain false, including parallel_execution.
- Maps RunRequest.prompt unchanged to one user ModelMessage in ModelRequest.
- Model content becomes COMPLETED RuntimeRunResult.
- ModelProviderError and unexpected ordinary exceptions become FAILED with
  `Model provider request failed`; unexpected exceptions are logged internally.
- Explicit asyncio cancellation becomes CANCELLED.
- Tracks active tasks per instance, cleans them in finally, and retains only
  lightweight terminal status history for later cancellation responses.
- Duplicate active IDs return FAILED (`Run is already active`) without replacing
  or cancelling the original task. Finished IDs may be reused.
- Cancellation is idempotent; unknown IDs return CANCELLED; finished IDs return
  their recorded status. Cancellation wins over late provider cleanup content.
- No events, stores, agent imports, provider selection, or provider shutdown.

NativeAgentAdapter still contains its own proven execution/cancellation code.
Do not remove that duplication or migrate it without an explicit migration step.

### Registry and resolver semantics

```python
RuntimeRegistry()
register(runtime_id: str, runtime: AgentRuntimePort) -> None
get(runtime_id: str) -> AgentRuntimePort | None
contains(runtime_id: str) -> bool
list() -> list[str]

RuntimeResolver(registry: RuntimeRegistry)
resolve(runtime_id: str) -> AgentRuntimePort
```

Registry keys are opaque exact strings. Registration rejects blanks and
duplicates with ValueError; duplicate rejection preserves the original instance.
Listing preserves insertion order and returns a fresh list. No runtime metadata
is inspected and no metadata-ID match is enforced.

Resolver returns the exact registered instance. Blank/unknown IDs raise
UnknownRuntimeError(ValueError), preserving the original `.runtime_id` with
message `Unknown runtime: <repr(id)>`. No normalization, defaults, construction,
metadata/capability checks, execution, mutation, configuration, or network calls.
RuntimeRegistry.get still returns None for unknown IDs.

## Validation baseline

Latest successful Step 16 results:

| Gate | Result |
| --- | --- |
| Targeted runtime/model/composition/architecture regression suite | 98 passed |
| `./scripts/test_all.sh` — backend | 304 passed |
| Backend Ruff / mypy | Clean; 56 source files checked |
| Frontend tests | 171 passed |
| Frontend configured TypeScript checks | Passed |
| Python client | 2 passed; Ruff/mypy clean |
| `./scripts/build_all.sh` | Passed, exit 0 |

The build script runs configured web/desktop frontend builds; this is not native
desktop packaging. Existing FastAPI/Starlette deprecation warnings and Vite
bundle-size warnings remain informational.

Automated validation must stay independent of Ollama, installed models,
credentials, and internet. FastAPI TestClient hangs inside this session's
restricted sandbox, even for old mock tests. Approved execution outside the
sandbox passed repeatedly. If that recurs, use the appropriate approval path;
do not weaken tests or mistake the sandbox limitation for an application bug.

Key tests: `test_runtime_port.py`, `test_native_runtime.py`,
`test_runtime_registry.py`, `test_runtime_resolver.py`, `test_native_agent.py`,
`test_model_provider_composition.py`, and `test_architecture.py` under
`backend/tests/`. Dedicated guards cover the runtime port, implementation,
registry, resolver, and RunService boundaries.

## Real local-model evidence from Step 12

- Ollama client/server: `0.33.3`.
- Installed model: `qwen2.5-coder:7b`, 4.7 GB.
- Compatible base URL: `http://localhost:11434/v1`.
- Process-local validation settings selected native/local and the installed
  model. No `.env` existed at that validation; no persistent settings changed.
- Discovery returned available=true, healthy, and the configured model identity.
- Prompt: `Reply with exactly: AVA LOCAL MODEL OK`.
- Actual assistant response: `AVA LOCAL MODEL OK`.
- HTTP 200, completed, approximately 11.46 seconds.
- Run ID: `46b21ac1-aefb-415c-b275-614823e45fd9`.
- Retrieved events: run_started → message_started → message_content → run_completed.
- A separate temporary instance targeting a refused local connection returned
  HTTP 200 with FAILED and run_started → run_failed. Public message:
  `The agent failed to complete the run.` No raw provider internals leaked.

Temporary validation servers were shut down. Those in-memory run IDs are evidence,
not retrievable records in a current server. Ollama was not stopped, installed,
or modified, and no model was downloaded. Runtime availability tomorrow should
be checked rather than assumed. No further live calls were needed for Steps 13–16.

## Known caveats to carry forward

- Synchronous POST /runs returns the AVA run ID only after completion, so an
  external client cannot practically cancel an active run through current routes.
  Automated cancellation tests remain authoritative; no API redesign was done.
- Cancellation is cooperative. A provider suppressing cancellation indefinitely
  can delay cleanup; cancelling local HTTP work does not guarantee remote
  inference stops.
- Terminal status history and run/event stores have no eviction/persistence.
- Provider generation uses an existing 30-second HTTP timeout, relevant to slow
  cold starts or long responses.
- Multi-provider shutdown lacks per-provider error isolation: one failing aclose
  can prevent later provider cleanup.
- Two ModelProviderError definitions exist: active code uses `ava.models.errors`;
  a separate legacy definition remains in `ava.models.providers.errors`.
  They were inspected but not consolidated. Do not assume they are aliases.
- No streaming, tools, RAG, compatibility validation, runtime discovery, external
  framework integration, or runtime UI was added.

## Safe resumption checklist

1. Inspect the current working tree and preserve all accumulated Phase 3 changes.
2. Read the next user-supplied prompt and reconcile it with the roadmap discrepancy.
3. Inspect actual contracts/composition before editing; the runtime stack is dormant.
4. Keep RunService behind AgentPort and model/runtime resolution independent.
5. Make only the authorized next-step changes with deterministic tests.
6. Run targeted regressions, `./scripts/test_all.sh`, and `./scripts/build_all.sh`
   as required by that step; update the implementation log with actual evidence.
7. Stop at the requested step boundary. Do not automatically continue the roadmap.
