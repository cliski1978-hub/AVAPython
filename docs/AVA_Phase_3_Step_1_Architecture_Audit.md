# AVA Phase 3 — Model and Agent Runtime Abstraction

## 1. Objective

Phase 3 turns AVA's existing abstraction boundaries into a working provider/runtime platform.

Sprint 2 already established:

```text
RunService
AgentPort
MockAgentAdapter
ModelProviderPort
RunStore
RunEventStore
AVA Run Contracts
```

Phase 3 will extend that architecture so AVA can independently select:

```text
Agent Runtime
      +
Model Provider
      +
Model
```

The central architectural rule is:

> An agent runtime must never be statically tied to a particular model or model provider.

Target architecture:

```text
                       AVA
                        |
              Run / Execution Layer
                        |
            +-----------+-----------+
            |                       |
      Runtime Resolver        Model Resolver
            |                       |
     Runtime Registry        Provider Registry
            |                       |
   AgentRuntimePort        ModelProviderPort
            |                       |
    +-------+-------+         +-----+------+
    |       |       |         |     |      |
  Native OpenHands LangGraph Local Corp External
                    |
                AgentCore
```

---

# 2. Development Method

Phase 3 should continue the controlled implementation method used successfully during Sprint 2.

Every step follows this cycle:

```text
1. Give Anvil ONE narrowly scoped implementation prompt.
2. Anvil inspects the existing implementation before modifying it.
3. Anvil implements only that step.
4. Targeted tests are added.
5. Existing tests must remain green.
6. Run the complete validation harness.
7. Anvil produces a completion report.
8. Review the work.
9. Only then issue the next prompt.
```

Never give Anvil an entire phase and ask it to implement everything.

---

# 3. Standard Anvil Prompt Format

Every implementation prompt should use approximately this structure:

```text
You are implementing AVA Phase 3, Step X.

FIRST:
Inspect the existing implementation and relevant architecture/documentation.
Do not assume the current code matches an earlier description.

GOAL:
<one narrowly defined outcome>

ARCHITECTURAL REQUIREMENTS:
<specific AVA boundaries that must be preserved>

IMPLEMENT:
<small set of required changes>

DO NOT:
<explicit exclusions>

TESTING:
<required targeted tests>

VALIDATION:
Run all relevant targeted validation followed by:
./scripts/test_all.sh

For TypeScript validation use the repository's existing validation convention.

DOCUMENTATION:
Update only documentation affected by this step.

STOP CONDITION:
When this step is fully implemented, tested, and documented, STOP.
Do not begin the next Phase 3 step.

COMPLETION REPORT:
Return:
1. Summary
2. Files changed
3. Architecture decisions
4. Tests added/changed
5. Validation results
6. Issues or risks discovered
7. Confirmation that no later Phase 3 work was implemented
```

This structure is important because it keeps coder agents from seeing the larger architecture and deciding to implement three additional features "while they are there."

---

# 4. Universal Phase 3 Guardrails

Every Anvil prompt should include these requirements where applicable:

```text
AVA owns the contracts.

Framework-specific code belongs behind adapters.

Do not make application code depend directly on:
- Ollama
- OpenAI
- OpenHands
- LangGraph
- AWS AgentCore
- any other specific runtime/provider.

Do not break the existing RunService/run-event lifecycle.

Do not remove the existing Mock implementation.

Do not replace AVA-owned contracts with framework-native contracts.

Do not introduce persistence, RAG, tool frameworks, or agent-driven document editing.

Do not perform unrelated refactoring.

Do not implement future Phase 3 steps.

Preserve Web/Desktop shared architecture.

All existing validation must remain green.
```

---

# 5. Step 1 — Phase 3 Architecture Audit

## Goal

Determine exactly what currently exists before changing any contracts.

## Anvil Task

Inspect:

```text
AgentPort
ModelProviderPort
MockAgentAdapter
RunService
RunStore
RunEventStore
ApplicationConfig
/run routes
capabilities endpoint
backend dependency/configuration wiring
existing tests
```

Produce:

```text
docs/AVA_Phase_3_Architecture_Audit.md
```

Document:

* current interfaces;
* current dependency direction;
* current implementations;
* existing configuration;
* where runtime/provider construction occurs;
* potential coupling;
* recommended files affected by Phase 3.

### Important

**No production code changes.**

### Completion Criteria

The architecture is understood before contracts are modified.

---

# 6. Step 2 — Define Model Capability Contract

## Goal

Create an AVA-owned description of model capabilities.

Possible normalized capabilities:

```text
chat
streaming
tool_calling
structured_output
vision
embeddings
reasoning
code_specialization
context_window
```

Do not connect these capabilities to a real provider yet.

Example concept:

```text
ModelCapabilities
ModelDescriptor
```

### Requirements

The objects must be:

* provider-neutral;
* serializable;
* testable;
* independent from Ollama/OpenAI SDK classes.

### Tests

Verify:

* construction;
* serialization;
* default values;
* capability combinations.

---

# 7. Step 3 — Define Runtime Capability Contract

## Goal

Create the equivalent capability description for agent runtimes.

Potential capabilities:

```text
tools
multi_agent
shell
filesystem
browser
code_execution
checkpointing
persistence
human_approval
parallel_execution
```

Example:

```text
RuntimeCapabilities
RuntimeDescriptor
```

### Important

Do not create a real runtime registry yet.

Do not integrate OpenHands.

---

# 8. Step 4 — Harden ModelProviderPort

## Goal

Review the existing `ModelProviderPort` and make it sufficient for real providers.

It should expose an AVA-owned request/response boundary rather than provider-specific types.

Conceptually:

```text
ModelProviderPort
    |
    +-- complete(...)
    +-- capabilities(...)
    +-- health/status
```

Streaming should only be added now if the existing architecture can support it cleanly without expanding scope substantially.

### Critical Rule

No OpenAI/Ollama-specific type may cross `ModelProviderPort`.

### Tests

Create contract-level tests using fake provider implementations.

---

# 9. Step 5 — Create Model Provider Registry

## Goal

Create a central backend registry for available model providers.

Conceptually:

```text
ModelProviderRegistry

register()
get()
contains()
list()
```

Example provider IDs:

```text
mock
local
corporate
external
```

These IDs are examples of AVA identities, not framework classes.

### Do Not

* implement Ollama;
* implement external APIs;
* modify the frontend.

---

# 10. Step 6 — Add Model Provider Configuration

## Goal

Allow AVA configuration to identify the default provider and model independently.

Conceptually:

```text
model_provider = "mock"
model_name = "mock-model"
```

Configuration should remain valid independently of agent runtime configuration.

### Tests

Verify:

```text
valid configuration
missing configuration behavior
unknown provider behavior
default behavior
```

---

# 11. Step 7 — Create Model Provider Resolver

## Goal

Resolve configured provider IDs through `ModelProviderRegistry`.

Conceptually:

```text
ApplicationConfig
       ↓
ModelProviderResolver
       ↓
ModelProviderRegistry
       ↓
ModelProviderPort
```

No provider-specific `if/else` logic should spread into `RunService`.

### Acceptance Test

Changing the configured provider should select another registered implementation without changing application code.

---

# 12. Step 8 — Implement OpenAI-Compatible HTTP Provider

## Goal

Create AVA's first real model-provider adapter.

Rather than making the first provider specific to one vendor, implement a configurable OpenAI-compatible HTTP adapter.

Conceptually:

```text
OpenAICompatibleModelProvider
    base_url
    model_name
    credentials/config
```

This can eventually support systems such as:

```text
Ollama OpenAI-compatible endpoint
company gateways exposing compatible APIs
other compatible model servers
```

### Important

Use AVA request/response objects outside the adapter.

Provider JSON stays inside the adapter.

### Tests

Use mocked HTTP responses.

Tests must not require a live network service.

---

# 13. Step 9 — Add Local Ollama Configuration

## Goal

Configure the OpenAI-compatible provider for a local Ollama deployment.

This is configuration and composition—not a second model architecture.

Example conceptual configuration:

```text
provider = local
base_url = http://localhost:11434/v1
model = configured local model
```

### Acceptance Criteria

AVA can resolve:

```text
local
→ OpenAICompatibleModelProvider
→ configured local endpoint
```

No changes should be required to the run architecture.

---

# 14. Step 10 — Add Provider Health and Discovery

## Goal

Allow AVA to determine whether configured providers are available.

Normalized state:

```text
available
unavailable
misconfigured
unknown
```

Provide an AVA-owned result rather than exposing raw provider errors.

### API

Extend the existing capabilities/configuration API where appropriate rather than creating duplicate architecture.

### Tests

Simulate:

```text
provider available
connection failure
invalid configuration
timeout/error
```

---

# 15. Step 11 — Connect the Native AVA Agent to ModelProviderPort

## Goal

Create the first genuine model-backed AVA execution path.

Current path:

```text
RunService
   ↓
AgentPort
   ↓
MockAgentAdapter
```

New available path:

```text
RunService
   ↓
AgentPort
   ↓
AVA Native Agent
   ↓
ModelProviderPort
```

The Mock Agent must remain available.

### Acceptance Criteria

A user message can flow:

```text
Frontend
→ /runs
→ RunService
→ Native Agent
→ ModelProviderPort
→ local model provider
→ AVA normalized events
→ UI
```

This is the first major Phase 3 vertical milestone.

---

# 16. Step 12 — Validate the Real Local Model Vertical Slice

## Goal

Stop adding architecture and thoroughly validate the first real model integration.

Test:

```text
successful completion
provider unavailable
model unavailable
provider error
cancellation
conversation isolation
retry
regenerate
run events
terminal event invariant
Web behavior
Desktop behavior
```

Do not add another runtime during this step.

### Milestone

At this point:

> AVA should be capable of running a real local LLM without changing its core application architecture.

---

# 17. Step 13 — Introduce AgentRuntimePort

## Goal

Separate runtime orchestration from individual agent behavior.

Create:

```text
AgentRuntimePort
```

Conceptually:

```text
start_run
cancel_run
capabilities
health/status
```

The exact contract should follow the current run architecture discovered during Step 1.

### Architecture

```text
RunService
    ↓
AgentRuntimePort
    ↓
Runtime Adapter
```

The runtime can then use:

```text
AgentPort
ModelProviderPort
Tools
```

without `RunService` knowing how it operates.

---

# 18. Step 14 — Wrap Existing AVA Execution as NativeRuntime

## Goal

Make the existing AVA run implementation the first implementation of `AgentRuntimePort`.

Conceptually:

```text
AgentRuntimePort
       ↓
NativeAgentRuntime
       ↓
AgentPort
       ↓
AVA Native Agent / Mock Agent
```

### Critical Requirement

This should primarily be an architectural move.

Existing behavior must remain unchanged.

All previous run lifecycle tests should continue passing.

---

# 19. Step 15 — Create Runtime Registry

## Goal

Create the runtime equivalent of `ModelProviderRegistry`.

Conceptually:

```text
RuntimeRegistry

native
openhands
langgraph
agentcore
```

Initially only `native` needs to be functional.

Registry metadata should include:

```text
runtime_id
display_name
capabilities
availability
```

---

# 20. Step 16 — Add Runtime Configuration and Resolver

## Goal

Allow AVA to resolve a configured runtime independently from its model.

Configuration now becomes conceptually:

```text
agent_runtime = native
model_provider = local
model_name = qwen...
```

These must remain separate settings.

### Required Test

Prove changing:

```text
agent_runtime
```

does not automatically change:

```text
model_provider
model_name
```

and vice versa.

This is one of the most important architecture tests in Phase 3.

---

# 21. Step 17 — Record Runtime and Model in Run Metadata

## Goal

Record which execution components were actually used.

Add normalized information such as:

```text
runtime_id
model_provider_id
model_name
```

to the appropriate AVA run metadata.

### Purpose

Future:

```text
debugging
auditing
performance testing
automatic routing
reproducibility
```

### Do Not

Add analytics infrastructure.

---

# 22. Step 18 — Add Runtime and Model Overrides to Run Requests

## Goal

Allow a run to optionally override application defaults.

Conceptually:

```text
runtime_id: optional
model_provider_id: optional
model_name: optional
```

Resolution order should be explicit.

For example:

```text
Run Override
     ↓
Execution Profile
     ↓
Application Default
```

Execution profiles do not need to exist yet; the architecture can leave room for them.

---

# 23. Step 19 — Create Compatibility Validator

## Goal

Prevent invalid runtime/model combinations before execution.

Example:

```text
Task requires tool calling

Selected Runtime:
supports_tools = true

Selected Model:
supports_tool_calling = false

Result:
Compatibility failure
```

The validator should operate exclusively on AVA capability contracts.

It must not contain code such as:

```text
if model == "qwen..."
if runtime == "openhands..."
```

unless an adapter is supplying its own capabilities.

---

# 24. Step 20 — Add Runtime/Model Discovery API

## Goal

Allow clients to ask AVA what is available.

Conceptually:

```text
GET /capabilities

available runtimes
available providers
available models
capabilities
health
defaults
```

Prefer extending the existing AVA capabilities concept rather than creating parallel APIs unnecessarily.

---

# 25. Step 21 — Add Model and Runtime Selection to API Client

## Goal

Expose Phase 3 backend selection/discovery features through `@ava/api-client`.

Add typed AVA-owned client contracts for:

```text
available runtimes
available providers/models
current defaults
run overrides
```

### Do Not

Build UI controls yet.

---

# 26. Step 22 — Add Runtime/Model Selection UI

## Goal

Expose selection to users without complicating the normal chat experience.

Conceptually:

```text
Runtime
Auto
AVA Native
OpenHands
LangGraph
AWS AgentCore

Model
Auto
Local / ...
Corporate / ...
External / ...
```

Initially only currently available options should be selectable.

Unavailable runtimes may be displayed as unavailable if useful.

### Important

Default user behavior remains simple:

```text
Runtime = Auto/default
Model = Auto/default
```

Advanced users gain manual control.

---

# 27. Step 23 — Create Execution Profile Contract

## Goal

Create an AVA-owned reusable configuration representing an execution strategy.

Example:

```text
ExecutionProfile

id
display_name
runtime_id
model_provider_id
model_name
required_capabilities
```

Potential future profiles:

```text
General Chat
Local Coding
Engineering Knowledge
Complex Agent Workflow
```

### Do Not

Implement automatic profile selection yet.

---

# 28. Step 24 — Implement Deterministic Auto Selection

## Goal

Create the first runtime/model router.

Do **not** use an LLM to make routing decisions yet.

Use deterministic capability-based logic:

```text
Request
   ↓
Required Capabilities
   ↓
Runtime candidates
   ↓
Model candidates
   ↓
Compatibility Validator
   ↓
Selected Execution Configuration
```

Manual user overrides must take precedence where appropriate.

---

# 29. Step 25 — OpenHands Adapter Skeleton

## Goal

Introduce OpenHands behind `AgentRuntimePort`.

At this step implement only:

```text
adapter class
configuration
registration
capability reporting
health/availability detection
dependency isolation
tests
```

### Do Not

Execute real OpenHands workflows yet.

The purpose is proving the adapter boundary.

---

# 30. Step 26 — OpenHands Minimal Execution

## Goal

Execute one minimal AVA run using OpenHands.

Required flow:

```text
AVA RunService
     ↓
OpenHandsRuntimeAdapter
     ↓
configured ModelProvider
     ↓
OpenHands execution
     ↓
AVA normalized run events
```

### Critical Test

Run OpenHands using a model selected through AVA.

OpenHands must not select or hardcode its own AVA model configuration.

---

# 31. Step 27 — OpenHands Runtime Validation

## Goal

Test the runtime thoroughly before introducing another runtime.

Test:

```text
normal run
failure
cancellation
provider failure
runtime unavailable
event translation
model override
runtime override
run metadata
```

Also verify:

```text
OpenHands + Local Provider
```

and, if another test provider exists:

```text
OpenHands + alternate provider
```

The same OpenHands adapter should work with both.

---

# 32. Step 28 — LangGraph Adapter Skeleton

## Goal

Introduce LangGraph behind the exact same runtime abstraction.

Implement only:

```text
configuration
adapter
registration
capabilities
health
tests
```

No complex graphs yet.

---

# 33. Step 29 — LangGraph Minimal Execution

## Goal

Run one simple LangGraph workflow through AVA.

Architecture:

```text
RunService
   ↓
LangGraphRuntimeAdapter
   ↓
AVA-selected ModelProvider
```

Again, LangGraph must not dictate which model provider AVA uses.

---

# 34. Step 30 — AWS AgentCore Adapter Skeleton

## Goal

Introduce the enterprise AWS runtime boundary without coupling AVA to it.

Implement:

```text
configuration
adapter
registry integration
capabilities
health detection
tests
```

No production enterprise workflow is required yet.

Authentication/configuration should remain isolated inside the adapter/infrastructure layer.

---

# 35. Step 31 — AWS AgentCore Minimal Execution

## Goal

When the appropriate environment is available,
