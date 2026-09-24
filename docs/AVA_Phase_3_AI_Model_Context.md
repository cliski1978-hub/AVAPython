# AVA Phase 3 — AI Model Context and Architecture Guide

## Document Purpose

This document is the canonical Phase 3 context for AI coding agents, reasoning models, and automated development assistants working on the AVA repository.

It is intentionally explicit.

An AI agent reading this document should be able to understand:

- what Phase 3 implemented;
- why the architecture exists;
- which components own which responsibilities;
- which boundaries must not be violated;
- how model identity differs from provider identity;
- how model selection, qualification, resource management, and execution fit together;
- what was verified at Phase 3 completion;
- what Phase 3 intentionally did not implement;
- which assumptions are safe for future development;
- which architectural invariants must survive later phases.

This document describes the completed Phase 3 state.

---

# 1. Phase 3 Status

## Final Status

```text
PHASE 3 — COMPLETE / PASS
```

Final completed sequence:

```text
Step 36 — Runtime / Tool Security Hardening              PASS
Step 37 — Multi-Model Architecture Audit                 PASS
Step 38 — Stable Model Identity / Provider Cardinality   PASS
Step 39 — Hosting Mode / Deployment Classification       PASS
Step 40 — Model Registry v1                              PASS
Step 41 — Qualification Metadata Integration             PASS
Step 42 — Deterministic Model Orchestrator                PASS
Step 43 — Model Resource Manager                         PASS
Step 44 — Multi-Model Execution + Final Validation       PASS
```

The final Phase 3 validation completed successfully.

Backend:

```text
591 passed
2 skipped
Ruff PASS
strict mypy PASS
93 backend source files checked
```

Python client:

```text
10 passed
Ruff PASS
strict mypy PASS
```

Frontend:

```text
@ava/contracts      11 passed
@ava/api-client     23 passed
@ava/ui-core        20 passed
@ava/agent-ui       125 passed
@ava/document-core  11 passed
@ava/workspace      12 passed
4 intentional integration skips
```

Builds:

```text
Web production build       PASS
Desktop production build   PASS
```

Aggregate validation:

```text
scripts/test_all.sh         PASS
```

Phase 3 is complete.

---

# 2. Phase 3 Goal

Phase 3 establishes AVA's stable multi-model execution foundation.

The goal is not simply to support more than one model.

The goal is to ensure that AVA can represent, select, qualify, bind, allocate, and execute models without coupling model identity to:

- a provider;
- an agent runtime;
- an inference engine;
- a workspace;
- tool permissions;
- hosting location;
- one physical machine;
- one model family.

The architecture must support a changing population of models without redesigning AVA Core.

The central principle is:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Model ≠ Inference Runtime
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

A single provider may serve multiple models.

A runtime may work with multiple providers and models.

A model may eventually be available through different inference paths.

Changing a model must never silently change workspace or tool permissions.

---

# 3. Architectural Position

The Phase 3 multi-model execution path is conceptually:

```text
RunService
    ↓
AgentPort
    ↓
ExecutionSelector
    ↓
ModelOrchestrator
    ↓
ModelSelectionDecision
    ↓
stable AVA model_id
    ↓
ModelRegistry / ModelProfile
    ↓
ModelBindingResolver / model_binding_from_profile
    ↓
ModelResourceManager
    ↓
ModelLease
    ↓
ConfiguredModelBinding
    ↓
Model Provider / Runtime execution path
    ↓
RuntimeRunResult
```

This is a layered architecture.

Do not collapse these responsibilities together.

---

# 4. Stable Model Identity

## 4.1 `model_id`

Phase 3 introduces a stable AVA-owned model identity:

```text
model_id
```

`model_id` identifies a model inside AVA.

It is not the same thing as:

```text
provider_id
provider_model_name
```

Example:

```text
provider_id = local

model_id = local-coder-a
provider_model_name = qwen-coder-a

model_id = local-coder-b
provider_model_name = qwen-coder-b
```

Both models are served by the same provider.

They remain distinct AVA models.

This distinction is essential.

Incorrect assumption:

```text
provider_id == model_id
```

Incorrect assumption:

```text
one provider == one model
```

Correct model execution must preserve `model_id` all the way from selection to resource leasing and binding.

---

# 5. Provider Cardinality

Phase 3 explicitly supports:

```text
one provider → many models
```

A provider describes the communication/execution path.

A model describes a specific model identity and capability profile.

Therefore:

```text
Provider
├── Model A
├── Model B
├── Model C
└── future models
```

The provider must not become the model catalog itself.

Provider identity must never be used as a substitute for model identity.

---

# 6. Hosting Mode

Phase 3 introduces deployment/hosting classification.

Canonical hosting modes are:

```text
local
company_hosted
external
```

Hosting mode is policy metadata.

It is used as a hard eligibility input during model selection.

Example:

```text
request policy = local_only
```

means:

```text
local model          eligible if other requirements pass
company_hosted       rejected
external             rejected
```

A high-scoring model does not override hosting policy.

Hard policy filters are applied before ranking/selection.

---

# 7. Model Registry v1

Phase 3 introduces `ModelRegistry`.

The registry answers:

> What AVA models exist?

It is a catalog.

It is not:

- a router;
- a GPU scheduler;
- a runtime;
- a provider implementation;
- a qualification engine;
- a workspace permission store.

A model profile contains public-safe and execution-relevant metadata such as:

```text
model_id
display name
provider_id
provider model identity
hosting mode
capabilities
enabled state
resource estimates where available
license/commercial-use metadata where supported
```

The exact current source should be treated as authoritative for field names.

The registry remains logically separate from live resource state.

Do not put mutable residency state such as `HOT` or active lease counts into `ModelProfile`.

---

# 8. Model Discovery

Phase 3 adds safe model discovery.

Conceptually:

```text
GET /models
```

returns public-safe model information.

The discovery surface must not expose:

- credentials;
- provider secrets;
- internal endpoints unless explicitly approved;
- local filesystem model paths;
- runtime handles;
- workspace permissions;
- security policy internals.

Discovery is read-only.

Discovery must not trigger inference.

Discovery must not load models.

---

# 9. Qualification Metadata

Phase 3 separates:

```text
declared capability
```

from:

```text
measured qualification
```

This is a critical distinction.

A model profile may declare:

```text
coding
tool_calling
planning
document_analysis
```

but AVA should not assume that the declared capability proves the model performs that function reliably.

Measured qualification metadata is stored separately and keyed by stable `model_id`.

Qualification may represent evidence such as:

- tool-call correctness;
- schema validity;
- repository navigation;
- failure recovery;
- test repair;
- long-loop stability;
- workspace boundary compliance;
- prompt-injection resistance;
- latency;
- correctness;
- successful task completion.

Phase 3 integrates qualification metadata into deterministic model eligibility/selection.

The registry itself remains a catalog.

Qualification state must not be merged into mutable `ModelProfile` resource state.

---

# 10. Deterministic Model Orchestrator

Phase 3 introduces `ModelOrchestrator`.

The orchestrator answers:

> Which eligible model should perform this task under the current constraints?

The real selection seam is:

```text
ModelOrchestrator.select(...)
    ↓
ModelSelectionDecision
```

The orchestrator is deterministic in Phase 3.

It does not use:

- learned routing;
- stochastic routing;
- adaptive exploration;
- contextual bandits;
- autonomous model installation.

The same effective inputs should produce the same effective selection result.

---

# 11. Model Selection Filters

Phase 3 selection includes hard eligibility filtering.

Important dimensions include:

```text
enabled state
hosting policy
provider constraint
declared capabilities
measured qualification
```

Resource feasibility may participate through the execution/resource path as the architecture evolves.

Hard filters occur before any preference ranking.

An ineligible model is not rescued by a high score.

---

# 12. ModelSelectionDecision

The orchestrator returns a decision object.

Conceptually it represents:

```text
selected model_id
selection result
selection reasoning / metadata where supported
```

Downstream execution must honor this decision.

A critical Phase 3 invariant is:

```text
selected model_id
```

must not be discarded and replaced by:

```text
provider_id
```

later in execution.

---

# 13. Binding Resolution

AVA must translate its stable model identity into provider execution identity.

The production binding path includes:

```python
model_binding_from_profile(profile)
```

which produces a binding equivalent to:

```python
ConfiguredModelBinding(
    model_id,
    provider_id,
    provider_model_name,
)
```

This binding preserves both:

```text
AVA identity:
    model_id

provider execution identity:
    provider_id
    provider_model_name
```

Do not remove `model_id` from this boundary.

Do not resolve a provider and then arbitrarily choose a model under that provider.

---

# 14. Model Resource Manager

Phase 3 introduces `ModelResourceManager`.

Its responsibility is:

> Make the already-selected model operationally available.

It does not decide which model is best.

Selection belongs to `ModelOrchestrator`.

Resource lifecycle belongs to `ModelResourceManager`.

These responsibilities must remain separate.

---

# 15. Model Resource States

Phase 3 models resource lifecycle with closed states equivalent to:

```text
COLD
WARM
LOADING
HOT
UNLOADING
UNAVAILABLE
```

These are operational states.

They do not belong in immutable model catalog metadata.

The source implementation uses typed state rather than arbitrary free-form strings.

---

# 16. Model Resource Descriptors

The resource manager uses model-specific descriptors.

Resource metadata is keyed by stable:

```text
model_id
```

not merely by provider.

This is required because one provider may serve multiple models with different:

- sizes;
- memory needs;
- lifecycle states;
- leases;
- future hardware placement.

---

# 17. Model Leases

Phase 3 introduces explicit model leases.

Conceptually:

```text
selected model
    ↓
ModelResourceManager.acquire(model_id)
    ↓
ModelLease
    ↓
execute
    ↓
release lease
```

The lease protects active model use.

Important invariant:

```text
model has active lease
→ unsafe unload is forbidden
```

Lease cleanup must occur on:

- success;
- failure;
- cancellation.

The selected model must be leased by `model_id`.

The sibling model under the same provider must remain untouched.

---

# 18. Resource Capacity

The resource layer is the correct future location for hardware capacity policy.

Primary local development target:

```text
64 GB system RAM
8 GB GPU VRAM
fast SSD/NVMe
```

The long-term architecture supports:

```text
many models stored on disk
selected models warm in RAM when practical
normally one large 7B–9B Q4-class model hot on an 8 GB GPU
safe transitions between models
small auxiliary models potentially elsewhere
```

Phase 3 establishes the seam.

It does not claim full real GPU scheduling.

---

# 19. Provider-Neutral Resource Adapters

The resource manager must not depend directly on a single engine.

Incorrect:

```text
ModelResourceManager → Ollama-specific logic embedded in core
```

Correct conceptual direction:

```text
ModelResourceManager
    ↓
resource adapter boundary
    ↓
provider / inference-runtime-specific implementation
```

This preserves future compatibility with:

```text
Ollama
llama.cpp
vLLM
SGLang
future engines
```

---

# 20. Current Production Resource Adapter

At Phase 3 completion, production resource management uses a truthful pass-through/provider-managed resource adapter.

This means Phase 3 does not falsely claim:

- real GPU telemetry;
- direct provider model loading;
- direct provider unloading;
- VRAM eviction;
- hardware-level residency control.

The architecture is real.

The provider-specific physical lifecycle implementation is deferred.

Do not fake GPU lifecycle merely to make the abstraction appear more complete.

---

# 21. NativeAgentAdapter Resource Integration

The current native execution path integrates resource leasing.

Conceptually:

```python
lease = await resource_manager.acquire(selected_model_id)

try:
    execute(...)
finally:
    await resource_manager.release(lease)
```

The real code should be inspected for exact signatures.

The invariant matters more than the exact syntax.

The lease must release on:

```text
success
provider failure
runtime failure
cancellation
```

---

# 22. Step 44 Integrated Multi-Model Proof

Phase 3 final integration added a focused proof that threads the real components together.

Test file:

```text
backend/tests/test_multimodel_execution_integration.py
```

The test uses one provider:

```text
provider_id = local
```

with two models:

```text
Model A
model_id = local-coder-a
provider_model_name = qwen-coder-a

Model B
model_id = local-coder-b
provider_model_name = qwen-coder-b
```

The real `ModelOrchestrator.select()` selects Model B.

The integrated proof verifies:

```text
decision.model_id
    ==
resource lease model_id
    ==
selected profile.model_id
    ==
ConfiguredModelBinding.model_id
```

and:

```text
ConfiguredModelBinding.provider_id
    ==
selected profile.provider_id
```

and:

```text
ConfiguredModelBinding.provider_model_name
    ==
selected profile.provider_model_name
```

The sibling Model A remains unleased and unbound.

---

# 23. Step 44 Regression Protected

The Step 44 integration test is specifically intended to catch this bug:

```text
provider "local" contains model A and model B

orchestrator selects model B

downstream code resolves only provider_id

model A is accidentally leased or invoked
```

That behavior is invalid.

Correct behavior preserves stable `model_id` through the entire path.

---

# 24. Step 44 Cleanup Proof

The integrated proof validates lease cleanup in three execution outcomes:

```text
success
failure
cancellation
```

All three pass.

This protects AVA from leaked model resource ownership.

---

# 25. RunService Boundary

A critical architectural invariant remains:

```text
RunService
    ↓
AgentPort
```

`RunService` must not directly understand:

- model registry;
- model orchestration;
- model resource manager;
- model binding internals;
- provider implementations;
- runtime implementations;
- Ollama;
- OpenHands;
- GPU lifecycle.

This protects AVA's application boundary.

Future AI coding agents must not "simplify" the architecture by injecting these dependencies into `RunService`.

---

# 26. Runtime Independence

Phase 3 model architecture is runtime-neutral.

Current and future runtimes include:

```text
NativeRuntime
OpenHandsRuntime
LangGraphRuntime
AWS AgentCore Runtime
future runtimes
```

Step 44 may validate through the native path, but model abstractions are not owned by NativeRuntime.

A future runtime must be able to consume the same model architecture without redesigning AVA Core.

---

# 27. Provider Independence

Phase 3 does not make AVA Core depend on:

```text
Ollama
OpenAI
LiteLLM
llama.cpp
vLLM
SGLang
```

These belong behind adapters or provider boundaries.

Future AI agents must preserve this isolation.

---

# 28. Workspace and Tool Security Independence

Model selection must never grant:

```text
workspace access
filesystem access
write permission
shell permission
network permission
browser permission
code execution
tool permissions
sandbox permissions
```

These are separate policy domains.

Correct:

```text
model selected
+
existing workspace/tool policy
```

Incorrect:

```text
stronger model selected
→ stronger permissions
```

There is no such automatic escalation.

---

# 29. Hosting Policy Is Security Policy

Hosting mode is not a preference score.

Example:

```text
local_only
```

means external or company-hosted models are ineligible even if they would otherwise be more capable.

Future adaptive routing must never weaken this rule.

---

# 30. Qualification Is Evidence, Not Identity

A model's qualification record does not change its identity.

Correct:

```text
model_id
→ qualification metadata
```

Incorrect:

```text
qualification creates a new model identity
```

Qualification should remain replaceable and updateable without breaking model references.

---

# 31. No Silent Fallback

Unknown model IDs and invalid execution combinations fail explicitly.

Do not silently substitute:

- another model;
- another provider;
- a default provider;
- a default model;

unless a future explicit fallback architecture authorizes and records that behavior.

Phase 3 intentionally favors deterministic, visible failure.

---

# 32. Unknown Model Behavior

Phase 3 includes direct coverage proving an unknown `model_id` fails explicitly without silently falling back to another catalog model.

This behavior must remain.

---

# 33. Cancellation Safety

Phase 3 includes cancellation cleanup coverage.

Cancellation must not leave:

- active leases;
- stuck resource ownership;
- false success;
- incorrect model state.

Future execution layers must preserve this property.

---

# 34. Architecture Guards

Phase 3 strengthened architecture guards.

Important boundaries include:

```text
orchestrator does not own resource lifecycle
resource manager does not own routing
resource manager does not import workspace/security policy
resource manager does not become provider-specific core logic
registry does not own mutable residency
RunService remains AgentPort-only
```

Architecture guard tests should be treated as product requirements, not disposable test implementation.

---

# 35. Public-Safe Metadata

Phase 3 public model surfaces must remain safe.

Do not expose:

```text
credentials
secret keys
internal provider credentials
sensitive endpoints
local model filesystem paths
workspace paths
permission grants
runtime handles
GPU process state
```

unless a later explicitly reviewed contract changes this policy.

---

# 36. Startup Behavior

AVA startup should remain passive where practical.

Application creation must not automatically:

```text
contact models
perform inference
load GPU models
download models
contact external providers
contact OpenHands services
acquire model leases
execute workspace commands
```

The model registry and orchestration components should be cheap to construct.

---

# 37. TestClient / Sandbox Validation Note

During final Step 44 validation, FastAPI `TestClient` initially appeared to hang.

Investigation proved this was not an AVA defect.

The session sandbox blocked AnyIO's cross-thread blocking portal.

Evidence:

- a blank FastAPI application hung inside the sandbox;
- a standalone AnyIO blocking portal hung inside the sandbox;
- both worked unchanged outside the sandbox;
- AVA `create_app()` completed;
- AVA lifespan ran normally in direct `asyncio.run()` execution.

Therefore no dependency downgrade or AVA architecture change was made.

The existing stack validated successfully outside the sandbox.

Observed versions at validation time:

```text
FastAPI   0.141.1
Starlette 1.6.0
HTTPX     0.28.1
AnyIO     4.12.1
```

Do not infer from the prior hang that these versions are known-bad for AVA.

The observed problem was execution-environment-specific.

---

# 38. Final Backend Validation

Final backend result:

```text
591 passed
2 skipped
4 existing OpenHands deprecation warnings
```

Ruff:

```text
PASS
```

Strict mypy:

```text
PASS
93 source files
```

---

# 39. Final Frontend Validation

Final package results:

```text
@ava/contracts      11 passed
@ava/api-client     23 passed
@ava/ui-core        20 passed
@ava/agent-ui       125 passed
@ava/document-core  11 passed
@ava/workspace      12 passed
```

There are:

```text
4 intentional integration skips
```

Recursive frontend TypeScript checks pass.

Web and Desktop production builds pass.

---

# 40. PromptComposer Test Note

Earlier reports mentioned two stale `PromptComposer` assertions expecting literal:

```text
Send
```

By final Phase 3 validation, the tests already correctly asserted the intended send-glyph behavior.

Final `agent-ui` tests:

```text
125 passed
```

No special Phase 3 fix remained necessary.

---

# 41. Aggregate Harness

The authoritative aggregate validation harness:

```text
scripts/test_all.sh
```

passed end-to-end at Phase 3 completion.

This is part of Phase 3 final evidence.

---

# 42. Phase 3 Definition of Done — Achieved

Phase 3 now provides:

```text
stable AVA model identity
provider/model separation
multiple models per provider
hosting classification
Model Registry v1
safe model discovery
qualification metadata
deterministic ModelOrchestrator
ModelResourceManager
resource leases
integrated model-selection execution
runtime-neutral model architecture
provider-neutral core architecture
workspace/tool security independence
complete green validation
```

---

# 43. Phase 3 Intentional Non-Goals

Phase 3 does not yet implement all future orchestration goals.

Do not treat the following as missing Phase 3 bugs:

```text
real GPU scheduling
real Ollama load/unload management
adaptive routing
learned routing
contextual-bandit routing
phase-aware multi-model switching
multiple model invocations inside one coordinated run
persistent invocation telemetry
specialist model training
automatic model installation
distributed resource scheduling
LangGraph model execution integration
AWS AgentCore model execution integration
full persistent model performance history
```

These belong to later roadmap work.

---

# 44. Phase-Aware Multi-Model Runs Are Future Work

Phase 3 proves:

```text
many models can exist
one selected model can be carried correctly through execution
```

Phase 3 does not yet mean:

```text
one run automatically uses planner model
→ coding model
→ reviewer model
→ writer model
```

That is later orchestration work.

Do not claim Phase 3 already implements multi-model switching within one run.

---

# 45. Model Resource Manager Is Not Yet a GPU Scheduler

The Phase 3 resource manager establishes:

```text
resource state
resource descriptors
leases
capacity seam
adapter seam
safe cleanup
```

It does not yet provide full physical GPU orchestration.

Future physical lifecycle implementations should plug into this seam rather than replace it.

---

# 46. Future Resource Adapter Direction

Future local execution may add adapters for engines such as:

```text
Ollama
llama.cpp
vLLM
SGLang
```

These adapters may eventually own engine-specific operations such as:

```text
load
unload
keep-alive
GPU layer configuration
context configuration
engine health
resource readiness
```

These details remain outside AVA Core.

---

# 47. Future Model Routing Direction

Later routing may evolve through:

```text
deterministic capability rules
→ weighted measured-performance scoring
→ performance-aware routing
→ controlled adaptive routing
```

The Phase 3 deterministic baseline must remain available for:

- testing;
- rollback;
- explainability;
- safe fallback.

Do not replace deterministic behavior wholesale when adaptive routing is added.

---

# 48. Future Qualification Direction

Future qualification should measure real AVA workloads.

Potential criteria include:

```text
correct tool choice
schema-valid arguments
minimal unnecessary tool usage
read-before-modify behavior
modify-then-validate behavior
test repair
failure recovery
repository navigation
long-loop stability
cancellation handling
workspace boundary compliance
prompt-injection resistance
truthful failure reporting
```

Public benchmarks may initialize expectations.

AVA-specific evidence should eventually determine production routing roles.

---

# 49. Future Invocation Telemetry

Later phases may introduce invocation-level identity such as:

```text
run_id
phase_id
invocation_id
model_id
provider_id
inference_runtime_id
agent_runtime_id
workspace_id
selection_decision_id
```

Phase 3 architecture deliberately leaves room for this.

Do not force telemetry into model identity or resource state.

---

# 50. Future Model Resource Scheduling

Long-term local hardware behavior may resemble:

```text
SSD/NVMe
    ↓
Model Library
    ↓
System RAM / warm cache
    ↓
GPU VRAM
    ↓
Active Model
    ↓
Inference
```

For the primary 8 GB GPU target, AVA should normally expect one larger quantized model hot at a time.

This is a resource policy, not a model-selection rule.

---

# 51. Future Fallback Architecture

Phase 3 does not introduce broad automatic fallback.

Future fallback must be:

```text
explicit
bounded
policy-compliant
observable
recorded
```

Examples of future reason codes may include:

```text
model unavailable
resource insufficient
provider timeout
capability mismatch
qualification failure
policy rejection
```

A `local_only` policy must stop before non-local fallback.

---

# 52. Future User Control

Future UX may support modes such as:

```text
auto
runtime_fixed
model_fixed
fully_fixed
```

Even user-forced model selection must continue to pass:

```text
existence
enabled state
policy
compatibility
resource feasibility
security
```

User preference does not override hard policy.

---

# 53. Future Specialist Models

AVA is designed to support specialist models for:

```text
software engineering
engineering specifications
robotics
PLC
technical documents
vision
manufacturing analysis
```

Specialist models should not become defaults based only on model-card claims.

They should be qualified in AVA's own workloads first.

---

# 54. One Application Principle

AVA remains one platform.

Do not fork separate core applications for:

```text
coding agent
specifications agent
engineering standards agent
robot optimization
root cause analysis
predictive maintenance
document workflows
```

Specialization should occur through:

```text
profiles
models
knowledge
tools
workflows
runtimes
workspace policy
```

inside the same AVA architecture.

---

# 55. What Future AI Agents Should Inspect First

When continuing development after Phase 3, inspect:

```text
backend/src/ava/models/
backend/src/ava/execution/
backend/src/ava/
backend/tests/
docs/AVA_Phase_3_Implementation_Log.md
docs/AVA_Multi_Model_Architecture_Audit.md
scripts/test_all.sh
```

Use actual repository code as the source of truth for exact current names.

Do not recreate abstractions from this document if equivalent components already exist.

---

# 56. High-Risk Refactors to Avoid

Future AI agents must be cautious about changes that:

```text
remove model_id from bindings
collapse provider_id and model_id
move resource lifecycle into orchestrator
move model ranking into resource manager
inject registry/orchestrator/resource manager into RunService
put workspace permissions into ModelProfile
make provider own global routing
make registry mutable runtime state
make startup contact models automatically
introduce silent fallback
bind a runtime permanently to one model
bind a model permanently to one inference engine
```

These would regress Phase 3 architecture.

---

# 57. Safe Extension Pattern

Preferred future extension pattern:

```text
define stable contract
↓
add adapter / implementation behind contract
↓
wire in composition root
↓
add deterministic tests
↓
add architecture guards
↓
add integration proof
↓
run full validation
```

Do not bypass the established boundaries for convenience.

---

# 58. Phase 3 Canonical Invariants

Treat these as hard architectural rules unless explicitly superseded by a reviewed architecture decision.

1. `model_id` is AVA's stable model identity.
2. `provider_id` is not a model identity.
3. One provider may serve multiple models.
4. Model selection and resource lifecycle are separate responsibilities.
5. Model registry and live resource state are separate.
6. Declared capability and measured qualification are separate.
7. Hosting policy is a hard eligibility filter.
8. Model selection cannot grant permissions.
9. Workspace/tool security remains independent from model choice.
10. `RunService` remains `AgentPort`-only.
11. Core model architecture remains runtime-neutral.
12. Core model architecture remains provider-neutral.
13. Provider-native model names stay behind binding/provider boundaries.
14. Active leases prevent unsafe resource release/unload.
15. Leases release on success, failure, and cancellation.
16. Unknown model IDs fail explicitly.
17. No silent fallback exists unless explicitly designed.
18. Discovery remains public-safe and read-only.
19. Startup does not automatically perform inference/model loading.
20. Deterministic routing is the Phase 3 source of truth.
21. Adaptive routing must preserve deterministic rollback.
22. Model/resource abstractions must not be rewritten around Ollama.
23. Phase 3 does not claim phase-aware model switching yet.
24. Phase 3 does not claim real GPU scheduling yet.
25. Full repository validation must remain green after future changes.

---

# 59. Phase 3 Final Architecture Summary

At Phase 3 completion, AVA can represent:

```text
Provider: local
    ├── Model: local-coder-a
    ├── Model: local-coder-b
    └── future models
```

and safely perform:

```text
task requirements
    ↓
ModelOrchestrator
    ↓
selected stable model_id
    ↓
ModelProfile
    ↓
resource lease for exact model_id
    ↓
provider binding for exact model
    ↓
runtime/provider execution
    ↓
lease cleanup
```

without confusing:

```text
provider identity
```

with:

```text
model identity
```

and without changing:

```text
workspace security
tool permissions
runtime security
```

This is the primary achievement of Phase 3.

---

# 60. Final AI Instruction

When modifying AVA after Phase 3:

- inspect before editing;
- preserve stable model identity;
- preserve provider/model separation;
- preserve runtime/model independence;
- preserve workspace/tool security independence;
- keep routing, registry, resource lifecycle, provider execution, and runtime execution as separate concerns;
- use adapters for engine-specific behavior;
- add integration tests that prove real cross-layer behavior;
- keep full-suite validation green;
- do not claim later roadmap capabilities until they are actually implemented.

Phase 3 is complete.

Future work must extend this foundation, not bypass it.
