# Phase 5.71 — Execution Context Injection

Phase 5.71 connects the resolved CORE prompt set from Phase 5.70 and Project
instructions from Phase 5.64/5.65 to real model execution. The effective
context is assembled in AVA before the runtime/provider boundary:

```text
AVA root system prompt
Resolved CORE prompts, in resolver order
Non-empty Project instructions
Existing conversation history, unchanged and in order
Current user message
```

## Root prompt ownership

The code audit found no existing product-owned root/system prompt construction
path: the native runtime previously translated the constructed conversation
messages directly into `ModelRequest`. Training data and test fixtures were
not product prompt ownership. Phase 5.71 therefore introduces the immutable
application baseline `AVA_ROOT_SYSTEM_PROMPT` in
`backend/src/ava/services/execution_prompt_context_service.py`. The
`ExecutionPromptContextService` owns assembly and inserts this root layer
before every subordinate instruction. It is not a `CorePromptRecord`, is not
stored in prompt persistence, and is not editable in System Prompts settings.

`ExecutionPromptLayers` is the AVA-owned structured execution contract. It
preserves root text, CORE prompt ID/name/category/text and winning-scope
provenance, plus optional Project instruction text. Only the resolver's
`enabled_prompts` are copied into the execution context. Assignment rows and
disabled prompt text are not injected. CORE text order is exactly the resolver
order; execution does not sort or re-resolve it.

## Resolution and timing

The application composes one `EffectivePromptResolver` over the same prompt,
assignment, and conversation repositories used by the 5.70 preview endpoint.
That resolver is passed to `ExecutionPromptContextService`. For each native
agent execution, AVA first selects the actual runtime, then resolves once with
that runtime's registry key and the canonical active AVA capabilities. Runtime
identity is not inferred from model provider identity. The service uses the
resolver's canonical conversation context for Project and Folder membership;
provider adapters do not query membership or assignments.

If the resolved conversation belongs to a Project, the service loads that
Project from the canonical repository. Non-empty instructions are retained
byte-for-byte as authored (including leading/trailing whitespace). `null`, an
empty string, or whitespace-only content produces no Project system message;
this affects execution only and does not change the persisted distinction
between null and empty values. Archived Projects continue to supply
instructions and Project-scope CORE assignments because archiving preserves
membership. Project deletion already clears the conversation relationship,
so later runs receive neither Project instructions nor Project-scope prompts.
An unexpected stale Project reference or resolver/repository failure fails the
run with the existing `configuration_invalid` taxonomy rather than silently
dropping context.

Resolution occurs at execution start. A retry/regenerate resolves the current
persisted configuration. Assignment or Project-instruction edits during an
active run do not mutate the already-built request; a later run sees the new
configuration. No durable prompt snapshot or long-lived cache was introduced.

## Execution and adapters

The narrow injection point is `NativeAgentAdapter`, after runtime selection
and compatibility validation and before context-window fitting/execution. The
same `RunContext.prompt_layers` flows into normal and streaming execution.
`execution_context_messages` prepends system layers while preserving the
existing history order and current-user message. The native runtime translates
those AVA-owned roles/texts directly into `ModelRequest`, which lets
OpenAI-compatible providers receive ordered separate system messages without
provider-specific resolution logic. The OpenHands boundary accepts one user
message, so its adapter renders deterministic `[AVA ROOT SYSTEM]`, `[AVA CORE
PROMPT: …]`, and `[PROJECT INSTRUCTIONS]` boundaries before the unchanged
conversation transcript. Both paths retain root-first ordering.

The mock agent remains a deterministic test adapter and does not call a model;
real model execution uses the native adapter and the same provider-independent
AVA context contract. Model/provider selection and capability/tool permissions
are unchanged. Prompt choice does not widen permissions or affect execution
selection. This phase adds no UI, API/client shape, Project execution default,
Folder free-form instruction, Conversation free-form instruction, or Project
file/RAG behavior.

Diagnostic logging records effective prompt IDs and whether Project
instructions are present; it does not log prompt text. Context resolution
failures log a safe error code and return safe run content. The resolved prompt
metadata is not persisted as a durable run snapshot.

## Validation

Focused tests cover resolver parity, root-only execution,
Global/Runtime/Capability/Project/Folder/Conversation resolution, overrides,
exact layer order, Project instruction behavior, normal and streaming parity,
retry timing, mid-stream edits, OpenHands translation, and failures before
provider invocation. Mutation testing confirmed that removing the
`NativeAgentAdapter` prompt-context builder breaks the root/CORE/Project order
integration test.

The canonical test harness, architecture repair, attachment restart-recovery
investigation, and live local-model checks completed in Phase 5.71A. The
attachment test's sandbox-only portal stall, schema-16 canonical service,
local marker and Project executions, current-config retry, and all aggregate
test/static-check results are documented in
[AVA_Phase_5_71A_Execution_Validation_Stabilization.md](AVA_Phase_5_71A_Execution_Validation_Stabilization.md).
Phase 5.71 is fully validated and complete.
