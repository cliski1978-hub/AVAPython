# AVA Phase 3 — Human Developer Documentation

## 1. Overview

Phase 3 completes AVA's first full multi-model architecture foundation.

The phase moves AVA from a system that can communicate with configurable model providers into a system that can represent and select distinct models, distinguish model identity from provider identity, classify where models are hosted, attach qualification evidence, manage model resource ownership, and carry a selected model safely through execution.

Final status:

```text
PHASE 3 — COMPLETE / PASS
```

Completed steps:

```text
36  Runtime / Tool Security Hardening
37  Multi-Model Architecture Audit
38  Stable Model Identity / Provider Cardinality
39  Hosting Mode / Deployment Classification
40  Model Registry v1
41  Qualification Metadata Integration
42  Deterministic Model Orchestrator
43  Model Resource Manager
44  Multi-Model Execution + Phase 3 Final Validation
```

---

# 2. Why Phase 3 Was Needed

AVA is intended to support:

- local models;
- company-hosted models;
- approved external models;
- multiple agent runtimes;
- future specialist models;
- future multi-model routing;
- constrained local hardware;
- enterprise security policy.

That requires AVA to separate several concepts that are often incorrectly merged in simpler AI applications.

The key separation is:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Model ≠ Inference Runtime
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

A provider is how AVA communicates with a model.

A model is the actual AVA-visible model identity.

A runtime is the agent execution framework.

A workspace is an approved execution context.

None of those concepts should silently define the others.

---

# 3. Final Multi-Model Execution Flow

The Phase 3 execution path is conceptually:

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
ModelRegistry / ModelProfile
    ↓
Model binding
    ↓
ModelResourceManager
    ↓
ModelLease
    ↓
ConfiguredModelBinding
    ↓
Provider / Agent Runtime
```

`RunService` remains intentionally unaware of multi-model internals.

This boundary is important because it keeps the application layer stable while model and runtime infrastructure evolves.

---

# 4. Stable Model Identity

Phase 3 introduces stable AVA model identity through:

```text
model_id
```

`model_id` is different from:

```text
provider_id
provider_model_name
```

For example:

```text
provider_id = local

model_id = local-coder-a
provider_model_name = qwen-coder-a

model_id = local-coder-b
provider_model_name = qwen-coder-b
```

Both models use the same provider.

AVA still treats them as separate models.

This prevents a common architectural bug where selecting a provider accidentally determines the model.

---

# 5. One Provider, Multiple Models

The architecture supports:

```text
Provider
├── Model A
├── Model B
└── Model C
```

This becomes especially important for local inference.

For example, a single local provider may eventually expose several installed models through one inference engine or compatible API.

The provider determines communication behavior.

The model registry determines which AVA models exist.

---

# 6. Hosting Classification

Phase 3 adds hosting mode metadata.

Current categories:

```text
local
company_hosted
external
```

These values participate in model eligibility.

Example:

```text
policy = local_only
```

means non-local models are rejected before model selection.

Hosting restrictions are treated as policy, not preference.

---

# 7. Model Registry v1

`ModelRegistry` is AVA's model catalog.

Its job is to describe what models exist and make their metadata available to the rest of the application.

A model profile may describe:

- stable model ID;
- display name;
- provider ID;
- provider-native model name;
- hosting mode;
- declared capabilities;
- enabled state;
- resource estimates;
- licensing metadata.

The registry is not responsible for:

- choosing a model;
- loading a model;
- tracking active leases;
- workspace policy;
- tool policy.

This separation is deliberate.

---

# 8. Model Discovery

Phase 3 adds model discovery through AVA's API/client layers.

The public model-discovery surface is designed to expose safe metadata only.

It must not expose credentials, internal paths, permission grants, or provider secrets.

Discovery is read-only.

A model-discovery request must not trigger inference or model loading.

---

# 9. Qualification Metadata

Phase 3 separates declared capabilities from measured evidence.

For example, a model may declare that it supports:

```text
coding
tool_calling
planning
```

but AVA may separately track whether it has actually performed well in those areas.

Qualification metadata is keyed by `model_id`.

This gives AVA a future path toward routing based on actual measured behavior rather than relying entirely on vendor/model-card claims.

---

# 10. Deterministic Model Orchestrator

The `ModelOrchestrator` performs model selection.

Its central operation is:

```text
ModelOrchestrator.select(...)
→ ModelSelectionDecision
```

Phase 3 selection is deterministic.

The orchestrator considers existing eligibility constraints such as:

- model enabled state;
- hosting restrictions;
- provider requirements;
- declared capabilities;
- measured qualification.

Phase 3 intentionally does not use machine-learned routing.

That keeps behavior explainable and testable.

---

# 11. Model Binding

After AVA selects a stable model ID, the selected `ModelProfile` is translated into provider execution identity.

Production binding uses:

```python
model_binding_from_profile(profile)
```

to produce a `ConfiguredModelBinding` carrying:

```text
model_id
provider_id
provider_model_name
```

This is the boundary that preserves AVA identity while still giving the provider/runtime the information it needs to perform execution.

---

# 12. Model Resource Manager

Step 43 introduces the `ModelResourceManager`.

Its job is not to choose a model.

Its job is to manage the operational availability of a model that has already been selected.

This is the distinction:

```text
ModelOrchestrator:
    Which model should be used?

ModelResourceManager:
    How is that selected model made safely available?
```

Keeping those responsibilities separate is essential for future hardware-aware scheduling.

---

# 13. Resource States

Phase 3 models resource lifecycle through states equivalent to:

```text
COLD
WARM
LOADING
HOT
UNLOADING
UNAVAILABLE
```

These are live operational states.

They are intentionally not stored as mutable fields in the model catalog.

---

# 14. Model Leases

A selected model receives a resource lease before execution.

Conceptually:

```text
select model
↓
acquire model lease
↓
execute
↓
release lease
```

The lease prevents the model from being unloaded or invalidated while it is being used.

Lease cleanup is guaranteed on:

- normal completion;
- execution failure;
- cancellation.

---

# 15. Resource Adapter Boundary

AVA Core does not directly manage a specific inference engine.

The resource manager uses an adapter boundary so future implementations may integrate with:

- Ollama;
- llama.cpp;
- vLLM;
- SGLang;
- other engines.

At Phase 3 completion, production resource behavior remains a truthful provider-managed/pass-through implementation.

AVA does not falsely claim direct GPU model loading/unloading yet.

---

# 16. Local Hardware Direction

The primary local development target is:

```text
64 GB system RAM
8 GB GPU VRAM
fast SSD/NVMe storage
```

The long-term design assumes many models may be stored on disk while only a limited number are active in GPU memory.

For the current machine, a likely policy is one larger 7B–9B Q4-class model hot at a time.

Phase 3 establishes the software boundary needed for that future scheduler.

It does not implement full GPU scheduling yet.

---

# 17. Step 44 Integration Test

The final integration proof is implemented in:

```text
backend/tests/test_multimodel_execution_integration.py
```

The test creates two AVA models behind one provider:

```text
provider_id = local

local-coder-a → qwen-coder-a
local-coder-b → qwen-coder-b
```

The real `ModelOrchestrator.select()` selects:

```text
local-coder-b
```

The test verifies that the same model identity is used by:

- the selection decision;
- resource acquisition;
- the selected model profile;
- model binding;
- the execution edge.

The sibling model remains untouched.

---

# 18. Why the Step 44 Test Matters

Without this test, AVA could accidentally do this:

```text
select model B
↓
resolve provider "local"
↓
lose model identity
↓
invoke model A
```

The integration test makes that regression visible.

It proves that execution is based on:

```text
model_id
```

rather than only:

```text
provider_id
```

---

# 19. Cleanup Validation

The Step 44 integration test includes three outcomes:

```text
success
failure
cancellation
```

In every case, the selected model lease is released.

This prevents resource leaks and future unload deadlocks.

---

# 20. Security Boundaries Preserved

Phase 3 does not allow model selection to alter:

- workspace access;
- filesystem access;
- write access;
- shell access;
- network access;
- code-execution permission;
- browser permission;
- tool permission.

Model quality and execution permission are separate concerns.

This separation must remain in future development.

---

# 21. RunService Remains Stable

`RunService` still depends on:

```text
AgentPort
```

only.

It does not directly depend on:

- `ModelRegistry`;
- `ModelOrchestrator`;
- `ModelResourceManager`;
- provider implementations;
- runtime implementations.

This keeps AVA's application layer insulated from infrastructure changes.

---

# 22. Runtime Independence

Current runtimes include Native and OpenHands.

Future runtimes may include LangGraph and AWS AgentCore.

The Phase 3 model architecture is not specific to any of them.

A runtime should consume model selection/binding through AVA's abstractions rather than introduce a parallel model architecture.

---

# 23. Provider Independence

The architecture does not make AVA Core depend directly on:

- Ollama;
- OpenAI;
- LiteLLM;
- llama.cpp;
- vLLM;
- SGLang.

Provider-specific behavior belongs behind adapters.

This prevents future inference-engine changes from forcing core application rewrites.

---

# 24. Unknown Model Behavior

Unknown `model_id` values fail explicitly.

AVA does not silently select another model.

This behavior was explicitly tested in Step 43.

Silent fallback is intentionally deferred until AVA has a bounded, observable fallback design.

---

# 25. Cancellation Behavior

Cancellation releases resource leases safely.

This was added as explicit Step 43 coverage.

Future execution paths must preserve that property.

---

# 26. Architecture Guards

Phase 3 architecture guards protect responsibilities such as:

```text
orchestrator does not become resource manager
resource manager does not become router
resource manager does not depend on workspace/security policy
RunService remains isolated from model internals
registry does not become live resource state
```

These tests should be treated as architecture enforcement, not test noise.

---

# 27. Final Validation

Phase 3 final backend validation:

```text
591 passed
2 skipped
4 existing OpenHands deprecation warnings
```

Static checks:

```text
Ruff         PASS
strict mypy  PASS
93 source files
```

Python client:

```text
10 passed
Ruff PASS
strict mypy PASS
```

Frontend:

```text
contracts       11 passed
api-client      23 passed
ui-core         20 passed
agent-ui        125 passed
document-core   11 passed
workspace       12 passed
```

There are four intentional integration skips.

TypeScript checks pass.

Production builds:

```text
Web      PASS
Desktop  PASS
```

Aggregate validation:

```text
scripts/test_all.sh
PASS
```

---

# 28. AnyIO/TestClient Investigation

During final validation, `TestClient` initially appeared to hang.

The hang occurred inside:

```text
TestClient.__enter__()
```

before AVA startup or route execution.

Investigation showed the session sandbox blocked AnyIO's cross-thread blocking portal.

The same FastAPI/AnyIO code worked outside the sandbox.

No AVA code or dependency changes were required.

Observed stack:

```text
FastAPI   0.141.1
Starlette 1.6.0
HTTPX     0.28.1
AnyIO     4.12.1
```

The final backend suite passed outside the problematic sandbox execution context.

---

# 29. PromptComposer Validation Note

Earlier development reports referenced two old `PromptComposer` assertions expecting literal `"Send"` text.

By final Phase 3 validation, these tests already correctly reflected the intended send-glyph behavior.

Final result:

```text
agent-ui: 125 passed
```

No outstanding PromptComposer failure remains.

---

# 30. What Phase 3 Does Not Implement

Phase 3 intentionally stops before several more advanced capabilities.

Not yet implemented:

```text
real GPU model scheduling
direct Ollama load/unload
phase-aware model switching inside one run
adaptive model routing
learned routing
automatic model installation
persistent invocation telemetry
full performance-history routing
specialist model training
distributed scheduling
```

These are future increments.

---

# 31. Important Distinction: Multi-Model Foundation vs Multi-Model Run

Phase 3 means AVA can:

- represent many models;
- distinguish them correctly;
- select one deterministically;
- bind it correctly;
- acquire the correct model resource;
- execute without confusing provider and model identity.

It does not yet mean one run automatically switches among several models.

That later flow might eventually look like:

```text
planning → general reasoning model
coding → coding model
validation → reviewer model
final report → writing model
```

Phase 3 only builds the foundation required to make that safe.

---

# 32. Future Model Resource Work

Future resource-manager work may add:

- real hardware inventory;
- VRAM/RAM budgets;
- physical load/unload operations;
- active model eviction;
- warm-model caching;
- readiness timing;
- lease-aware switching;
- cancellation-safe loading;
- engine-specific lifecycle adapters.

Those changes should extend the existing resource-manager abstraction rather than replace it.

---

# 33. Future Routing Work

The likely routing evolution is:

```text
deterministic rules
↓
weighted capability/performance scoring
↓
measured AVA performance
↓
controlled adaptive routing
```

The deterministic Phase 3 implementation should remain available as a reliable baseline and rollback strategy.

---

# 34. Future Qualification Work

Future qualification should evaluate models using real AVA agent workloads.

Useful criteria include:

- correct tool selection;
- valid tool arguments;
- failure recovery;
- repository navigation;
- code repair;
- long-running agent stability;
- test execution;
- truthful completion;
- workspace-boundary compliance;
- prompt-injection resistance.

Qualification should remain separate from model identity.

---

# 35. Future Telemetry Work

A later phase may introduce invocation-level telemetry such as:

```text
run_id
phase_id
invocation_id
selection_decision_id
model_id
provider_id
agent_runtime_id
inference_runtime_id
workspace_id
latency
tokens
tool calls
outcome
```

Phase 3 leaves room for this without forcing it into current contracts prematurely.

---

# 36. Development Rules After Phase 3

When extending AVA, preserve these rules:

1. Keep `model_id` stable.
2. Never use `provider_id` as a replacement for model identity.
3. Allow multiple models per provider.
4. Keep model routing out of the resource manager.
5. Keep resource lifecycle out of the orchestrator.
6. Keep live residency state out of the registry.
7. Keep model choice separate from workspace/tool permissions.
8. Keep `RunService` dependent only on `AgentPort`.
9. Keep provider/inference SDKs behind adapters.
10. Keep startup passive.
11. Fail explicitly on unknown IDs.
12. Do not add silent fallback without a defined policy.
13. Keep deterministic routing testable.
14. Add architecture guards when introducing new seams.
15. Run the complete validation suite after architectural changes.

---

# 37. Developer Checklist for Future Multi-Model Changes

Before changing model infrastructure, answer:

```text
Does this change preserve stable model_id?
Does it preserve provider/model separation?
Does it preserve runtime/model independence?
Does it preserve workspace/tool security?
Is selection logic still in the orchestrator?
Is resource lifecycle still in the resource manager?
Are provider-specific details behind adapters?
Will unknown IDs still fail safely?
Will leases release on failure/cancel?
Does discovery remain public-safe?
Does startup remain passive?
Are integration tests proving the real cross-layer path?
```

If any answer is unclear, review the architecture before proceeding.

---

# 38. Recommended Files to Review

For future Phase 4+ work, start with the current repository versions of:

```text
backend/src/ava/models/
backend/src/ava/execution/
backend/tests/test_multimodel_execution_integration.py
docs/AVA_Phase_3_Implementation_Log.md
docs/AVA_Multi_Model_Architecture_Audit.md
scripts/test_all.sh
```

Exact source code remains authoritative for current names and signatures.

---

# 39. Phase 3 Final Result

Phase 3 gives AVA a real multi-model foundation.

AVA can now correctly distinguish:

```text
Which provider?
Which model?
Where is it hosted?
Is it eligible?
Is it qualified?
Which resource is being leased?
Which provider-native model name should execute?
```

without collapsing those questions into one setting.

That foundation is what future:

- multi-model orchestration;
- hardware-aware scheduling;
- specialist models;
- adaptive routing;
- phase-aware execution;

will build upon.

---

# 40. Final Status

```text
STEP 44 — COMPLETE / PASS
PHASE 3 — COMPLETE / PASS
```

Phase 3 should be treated as a completed architecture milestone.

Future work should extend it rather than redesigning around a single model, provider, runtime, or inference engine.
