# Phase 5.70 — Effective Prompt Resolver

Phase 5.70 adds an AVA-owned, provider-independent resolver that computes the
effective CORE prompt set for a preview context. It is read-only and stops
before run or provider request assembly.

## Context and scope support

Callers provide an optional `conversation_id`, `runtime_key`, and a collection
of AVA `CapabilityName` values. When a conversation is supplied, the resolver
loads its canonical record and derives its `project_id` and `folder_id`; callers
cannot provide contradictory membership. Archived conversations and archived
Projects remain resolvable because archive does not delete those records.

The applicable scopes are Global, Runtime, Capability, Project, Folder, and
Conversation. Application and Model Compatibility remain unsupported because
AVA has no stable assignable identities for them. Runtime keys are checked
against the configured runtime registry. Capability names use the existing AVA
capability enum. Missing conversations and unknown runtime/capability identities
return the existing not-found category through the preview API.

## Resolution rules

Specificity, broadest to narrowest, is:

```text
GLOBAL < RUNTIME < CAPABILITY < PROJECT < FOLDER < CONVERSATION
```

Each definition resolves independently. The resolver examines applicable
assignments from Conversation back to Global; the first explicit assignment
wins. A missing row is INHERIT and does not create an assignment. No applicable
assignment means the prompt is not effective. A narrower ENABLE can therefore
re-enable a definition disabled at a broader scope, and a narrower DISABLE
suppresses broader ENABLE assignments.

Multiple active capabilities occupy one precedence tier. If they assign the
same prompt with conflicting modes, any DISABLE wins. If modes agree, the
canonical capability-name order determines provenance. Neither repository
iteration order nor assignment timestamps decide semantic priority.

An explicitly disabled definition is excluded even if an applicable
assignment says ENABLE. Its assignments are retained, so re-enabling the
definition makes the existing assignments effective again. Project and Folder
are independent and may both participate; Folder is more specific than Project.
Missing membership and inactive Runtime/Capability targets do not participate.
Application and Model Compatibility assignments are not loaded into resolution.

## Result and ordering

`EffectivePromptSet` contains the canonical resolved context, enabled prompts,
and excluded prompts. Each `ResolvedCorePrompt` carries the definition fields
needed for later execution assembly plus effective state, explanation reason,
winning scope and identity, winning assignment mode, and assignment ID. Excluded
reasons identify disabled definitions, no matching assignment, and explicit
DISABLE decisions.

Enabled prompt ordering is deterministic: winning scope from broad to narrow,
then category, case-insensitive name, display name, and prompt ID. Within a
Capability tier, canonical capability identity is used for stable provenance;
it does not turn assignment time into priority. Category remains organizational
and does not outrank AVA root policy.

The resolver bulk-loads definitions once and reads assignment collections once
per applicable scope target, then performs the decisions in memory. It does not
write definitions, assignments, conversations, Projects, or folders.

## Preview API

`POST /core-prompts/resolve` accepts an optional conversation ID, runtime key,
and capability list. It returns the structured context, enabled prompts, and
excluded prompts with provenance. It does not return a canonical concatenated
system prompt and has no execution effect.

The typed `resolveCorePrompts` client method and shared request/response types
mirror this API. The preview does not modify `RunService`, `AgentPort`, runtime
or provider adapters, message assembly, Project instruction behavior, or model
payloads. The stack remains:

```text
AVA Root System
    ↓
Resolved CORE Prompts
    ↓
Scoped Custom Instructions
    ↓
Conversation History
    ↓
User Message
```

Only the resolved CORE prompt layer is implemented here. Execution injection
and Project-instruction assembly remain outside Phase 5.70.
