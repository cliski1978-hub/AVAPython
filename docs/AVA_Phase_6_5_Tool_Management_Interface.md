# AVA Phase 6.5 — Tool Management Interface

Date: 2026-10-13  
Status: implemented; default administrative restriction retained.  
Next bounded step: Phase 6.6, only after explicit owner authorization.

## Outcome and scope

Settings → Features & Tools now includes a dedicated **Tool Management** view with metadata, combined search/filter controls, per-tool draft switches, and expandable details. It extends the existing Phase 6.4 controller rather than adding another master gate, storage layer, API, or security policy.

The inspected Phase 6.2 contracts, 6.3 registry and 6.4 implementation exist in source. Phase 6.4's administrative boundary remains fail-closed: ordinary deployments have no authenticated feature-administration integration, so writes are denied and controls are read-only. This is the explicitly acceptable behavior in the Phase 6.5 request. No development bypass or allowing production administrator adapter was added.

The owner-locked master plan, Phase 6 outline and previous phase documents remain unchanged. No backend production code, API contract, database migration, runtime, handler, execution endpoint or approval workflow changed in this step.

## Components and reuse

- `frontend/packages/settings-core/src/sections/ToolManagementPanel.tsx`: descriptive tool view, transient filters, draft controls and details.
- `frontend/packages/settings-core/src/sections/ToolFeaturesSection.tsx`: integrates the panel with the existing master switch, confirmation behavior, versioned save, error/retry/success state and generation guards.
- `frontend/packages/settings-core/src/sections/tool-management.test.tsx`: six new metadata/filter/empty/theme/structure tests.
- `frontend/packages/settings-core/src/sections/tool-features.test.tsx`: additional integration regression proving filtered-out configured IDs remain in a complete save.
- This report.

Reused without duplicating: `ToolDefinition`, `ToolFeaturesResponse`, the existing registry, `ToolFeatureService`, repository/migration, trusted administrative port, GET/PUT `/settings/tool-features`, shared API-client wrappers, Settings navigation, semantic shadcn primitives, and the same Web/Desktop workspace composition. No new dependency or frontend state library was introduced.

## Inventory, search and details

Each row shows name, description, stable ID, execution category, risk, declared capabilities, approval metadata, saved configured state, effective feature availability and backend reason. Draft switches separately show an unsaved label when they differ from saved state. Tool identity is the ID, never the display name or filtered row index.

Search is case-insensitive and whitespace-trimmed over name/ID. Category, saved enabled/disabled state and risk filters intersect. Filters preserve backend ordering and match **saved** state, not draft changes; explanatory count text states this explicitly. Filters cannot enable a tool, modify permissions or narrow the stored configuration silently. Drafts for hidden rows remain in the complete versioned save payload.

Empty registry and no filter matches have distinct messages. No invented tool entries fill an empty production registry. Search/filter state is transient and resets when the version-keyed editor is reconstructed after save/reload; it is not persisted as security configuration.

Native expandable details provide identity/definition/contract version, bounded input/output schema summaries, required authorization explanation and approval semantics. Summaries report property/required counts and at most six top-level field names/types, truncating long names; large raw schemas are not printed in the main list or automatically rendered in details.

The inventory does **not** have executor/runtime-support metadata. It explicitly says compatibility and execution authorization are not reported; it does not fabricate “supported,” “authorized,” “approved,” or “operational” status from registration or an enabled feature. Backend invalid-configuration/framework-disabled/tool-disabled reasons remain visible and distinct. Unknown IDs are not listed or silently synthesized; their mutation rejection remains backend-owned.

## Configuration and administrative enforcement

The single Phase 6.4 master switch and per-tool preferences remain authoritative. Master off makes effective gates unavailable; individual controls are disabled while the master draft is off. New tools remain disabled until explicitly configured. Above-low-risk enablement retains the existing configuration confirmation. These confirmations are not human approvals for executing operations.

All successful saves require a backend response and use the loaded expected configuration version. Failed saves retain drafts without claiming success; conflicts provide reload guidance. Retry/loading/generation/in-flight guards are reused, including ignoring late responses after client changes or unmount and preventing duplicate saves.

Default read-only messaging and disabled mutations remain intact. The backend ignores client role headers and rejects unauthorized direct updates. `can_manage` is server display metadata, not an authority grant. A future trusted management channel must authenticate the current administrator or enforce a real deployment restriction; frontend visibility, CORS, loopback alone and a client boolean are not substitutes.

Responsibilities stay independent:

1. Registry: descriptive known tools.
2. Feature configuration: configured availability.
3. Execution authorization: later policy, Workspace/resource scope and approval checks.

No use-case definitions or allowlist configuration were added. The view consumes normalized definitions and backend-computed states, so future narrowing allowlists need not become a parallel frontend authorization engine.

## Accessibility and presentation

Shared Input/Switch controls and semantic card/background/foreground/border/focus tokens are used. Filters have labels/accessible names; row switches are named by tool; count/empty messaging uses status text; native details/summary support keyboard expansion. Descriptions/names/IDs wrap, containers use `min-w-0`, and the filter grid changes from one column to two/four at existing breakpoints.

Light/Dark/System behavior is tested through the actual AppearanceProvider and semantic-token structure. The same package is rendered by Web and Desktop. These tests do not prove pixel geometry at a native resized window or color contrast in a live WebView: jsdom provides no reliable layout engine. No manual browser/native GUI acceptance is claimed.

## Executed validation

| Check | Result |
| --- | --- |
| Backend feature security, registry and full architecture: `tests/test_tool_features.py tests/test_tool_registry.py tests/test_architecture.py` | **165 passed in 3.35s**. Includes existing unknown-tool denial, default unauthorized API denial, version conflicts, corrupt/default state, concurrency, no implicit permission and administrative withdrawal. |
| Backend Ruff, `src tests --no-cache` | **PASS**. |
| Strict mypy, backend `src` | **PASS**, 261 source files. |
| Aggregate `pnpm test` | **1,127 passed, 6 existing opt-in live-integration skips**, final run. |
| Settings package | **226 passed** in final aggregate; existing six feature-controller tests plus six management tests and the hidden-tool-save regression. |
| `pnpm lint` | **PASS** across shared packages/apps; final Settings typecheck also passed. |
| Web and Desktop frontend production builds | **PASS**, after final production UI changes. Existing large-chunk advisory only. |
| `git diff --check` | **PASS**. |

Existing Settings architecture guards passed without weakening browser-storage restrictions. Theme test fixtures use ui-core's owned appearance helpers, not feature persistence in browser storage. No backend gate/administration/schema guard was relaxed.

The backend API path is exercised by the existing in-process ASGI security tests, including the documented test-local worker-dispatch adapter for this host's AnyIO limitation. Production routing/security remain unchanged. This is not a live socket/identity integration certification. Wider backend `test_all.sh`, Bubblewrap execution and native GUI acceptance were not repeated; prior environment/fixture limitations remain recorded in Phase 6.4 and the phase audit.

No developer data was modified for validation. Production registry remains empty; mixed tool examples are test fixtures, not fake operational tools.

## Readiness and remaining limitations

Phase 6.5 is complete within the permitted read-only deployment boundary. Phase 6.6 can implement policy/Workspace authority after explicit owner authorization. Current administrator integration is still absent by default, and execution compatibility/authorization is intentionally unavailable metadata. Feature enablement must never be treated as permission by that later work.

No tool dispatch, handlers, Native/OpenHands integration, Workspace authority change, approval service, use-case configuration, RAG, engineering workflow, plugins or migrations were implemented. Phase 6.6 has not started.
