# AVA Python — Phase 6 Implementation Outline

**Phase:** 6 — Normalized Tool and Approval Framework  
**Status:** Planned  
**Objective:** Deliver secure, configurable, runtime-independent tool execution, with frontend-managed feature controls and backend-enforced permissions and approvals.

## Implementation Steps

1. **6.1 — Architecture audit:** Inspect Native AVA/OpenHands tool paths, existing Workspace security, run lifecycle, and persistence boundaries.
2. **6.2 — Normalized contracts:** Define AVA-owned tool definitions, requests, results, errors, and lifecycle events.
3. **6.3 — Tool registry:** Register and discover tools using stable IDs, schemas, capabilities, and risk classifications; leave room for future per-use-case allowlists.
4. **6.4 — Feature gates and Settings UI:** Create frontend controls for the tool framework and individual tools; persist selections, default to disabled, and enforce effective gates server-side.
5. **6.5 — Tool management UI:** Display available tools, configuration, risk levels, and reasons a tool is unavailable.
6. **6.6 — Policy and Workspace authority:** Enforce tool permissions, path containment, and read/write/execute boundaries independently of model and runtime; prepare to accept a fixed administrator-assigned Workspace for future use cases.
7. **6.7 — Durable approval framework:** Implement approval requests, decisions, denial, expiry, cancellation, and restart-safe state.
8. **6.8 — Approval UI:** Show exact requested operations and allow authorized approve/deny decisions.
9. **6.9 — Tool dispatcher and initial tools:** Normalize execution of file read/write/edit/delete and controlled commands, with authorization rechecked before side effects.
10. **6.10 — Runtime integration:** Connect Native AVA and OpenHands to the shared tool contracts; prove multi-step tool use without runtime-specific permission escalation.
11. **6.11 — Persistence and Run Inspector:** Record tool lifecycle, results, approval history, and historical execution context; support recovery and cancellation.
12. **6.12 — Security and final validation:** Test bypass attempts, disabled tools, Workspace isolation, approval revocation, runtime switching, Web/Desktop integration, and Phase 5 regressions; produce Phase 7 handoff.

## Phase Boundaries

**Included:** Generic tools, configurable availability, Settings controls, security policy, Workspace enforcement, human approvals, runtime-neutral execution, and durable inspection.

**Deferred:** Use-case definitions, use-case-specific tool assignments, standard-user use-case screens, contextual use-case assistants, RAG, and engineering-specific tool implementations.

**Exit criterion:** At least one AVA-defined tool operates through Native AVA and OpenHands with the same contract and validated feature gating, Workspace authorization, approvals where needed, persistence, and inspection.

**Development rule:** Implement and validate one bounded step at a time; stop for review before advancing. Preserve `RunService → AgentPort` and model/runtime/provider independence.

## Owner-approved additive implementation sequence

The owner approved a bounded production-security integration extension on 2026-10-14. The later implementation records use 6.11 for initial tool implementations, 6.12 for runtime integration, 6.12A for the mode selector, 6.13 for durable lifecycle, and 6.14 for Run Inspector; the numbering in this legacy outline is retained as historical planning context and completed work is not renumbered. The approved 6.14A–6.14D additions precede the existing 6.15 security/integration testing and 6.16 final validation/handoff. See [AVA Phase 6 Production Execution Integration Addendum](AVA_Phase_6_Production_Execution_Integration_Addendum.md) for owners, dependencies, acceptance criteria, security requirements, and validation gates. The locked canonical master plan was not changed.
