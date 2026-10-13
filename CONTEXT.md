# AVA Domain Context

AVA organizes conversations and related resources while keeping organizational groupings separate from execution concepts.

## Language

**Conversation Folder**:
A flat, AVA-owned organizational grouping that conversations may reference by ID, distinct from a Project. It does not define execution, workspace, knowledge, instruction, model, runtime, or file boundaries.

**Project**:
A durable AVA workspace and context boundary that may own conversations and related context. A conversation belongs to at most one Project and may belong to none. Unlike a Conversation Folder, a Project defines a workspace boundary rather than only organizing conversations.

**CORE System Prompt**:
An AVA-owned reusable prompt definition identified by an opaque ID. Its category organizes the definition and does not determine where it applies. Every enabled definition is included in the global prompt baseline for plain, Folder, Project, and Conversation runs. Scoped assignments override that baseline where they apply; an explicit disable can suppress a definition at a scope, and a nearer explicit enable can re-enable it. Project instructions remain separate Project-specific customization.

**CORE Prompt Assignment**:
An explicit enable/disable override for one reusable CORE prompt at one supported scope. It stores only prompt identity, scope identity, mode, and timestamps. No assignment row means INHERIT from the globally included enabled-definition baseline. Assignment storage does not itself resolve inherited prompt stacks.

**Project Execution Defaults**:
Independent Project preferences for a supported runtime key and a stable AVA model ID. Each may be unset independently. They reference resources owned by AVA configuration and do not make a Project the owner of a runtime or model.

**Project File**:
An AVA-owned data resource with exactly one Project owner. A Project File exists independently of any one conversation and is distinct from a Conversation Attachment. Its identity is separate from its filename, and its metadata is separate from its binary content. Filenames are unique within one Project after trimming surrounding whitespace and Unicode case-folding; separate Projects may use the same filename. The backend checks this before writing content, and relational persistence enforces the same Project-scoped normalized key.

**Conversation Attachment**:
An AVA-owned attachment associated with a conversation or message context under the attachment ownership model. It is distinct from a Project File, which belongs to a Project and survives independently of any one conversation.

Phase 5.76 implements Project Files metadata persistence, independent binary content storage, Project-scoped API operations, and typed API-client methods. Phase 5.77 adds Project-scoped list, upload, download, and delete UI in the Project workspace. Phase 5.78 defines a provider-neutral future Knowledge/RAG boundary: Project File IDs remain source identity, while source references, minimal Knowledge Documents, ingestion/retrieval ports, explicit scope, and provenance stay separate from the source resource. This boundary adds no ingestion, embeddings, vector index, retrieval behavior, API, UI, or execution integration. Knowledge ingestion, embeddings, vector indexing, retrieval, and execution integration remain unimplemented.

**Global Execution Defaults**:
Application-wide configured references used as the application's execution defaults. They are distinct from Project preferences and from an explicit selection attached to one run.

**Explicit Run Selection**:
A per-run request that names execution axes directly. It is distinct from both application-wide and Project default preferences.

**Runtime Key**:
The AVA registry identity for a supported agent runtime adapter, such as `native`. It is distinct from a configured runtime-configuration ID.

**Model ID**:
AVA's stable, provider-neutral identity for a configured model. It is distinct from provider identity, provider-connection identity, and the provider-native model name.

**Canonical durable state**:
Backend-owned resource state that remains authoritative across application and page reconstruction. Conversations, messages, Runs, Folders, Projects, prompt configuration, and Project Files are reconstructed from their owning durable stores; frontend views do not become a second owner of those resources.

**Transient UI state**:
Page- or process-local interaction state such as selection, expanded Folders, drag state, pending mutations, search text, and unsent composer text. It may reset on reload and does not override canonical durable state.

The SQLite migration registry is the authority for durable schema versioning.
After the initial schema baseline, the certified Phase 5 migration path is
forward-only and additive: historical schemas advance through ordered,
transactional migrations; new
Conversation Folder and Project membership, Project execution preferences, and
CORE prompt assignments remain nullable or absent for old records so an upgrade
does not fabricate organization, overrides, or execution choices. Conversation
Attachment metadata and Project File metadata/content are separate ownership
systems; migration never assumes an attachment blob is exclusively owned by one
conversation. The backend owns schema migration; frontend packages consume
current contracts and contain no schema-version migration logic.

Effective run selection is resolved independently for runtime and model using
this precedence:

```text
Explicit Run Override
→ Project Default
→ Application Default
→ Bootstrap Fallback
```

Project membership is derived from the canonical Conversation at execution
selection time. A stale Project runtime key and a missing or disabled Project
model are skipped for their own axis; application defaults retain their
existing strict validation when selected. Retries resolve current settings,
while a running request keeps the selection it already resolved. Project
execution defaults do not select providers: the selected model determines its
configured provider connection.

## Prompt and instruction context stack

```text
AVA Root System
    ↓
Resolved CORE Prompts                         IMPLEMENTED (Phase 5.70, injected 5.71)
    ↓
Project Instructions                          IMPLEMENTED (Phase 5.71)
    ↓
Conversation History
    ↓
User Message
```

Phase 5.70 resolves enabled CORE prompt definitions and scoped overrides into a
structured, provenance-bearing set. Unassigned definitions inherit the global
baseline and therefore apply at plain, Folder, Project, and Conversation
scopes; nearer explicit assignments may override that baseline. Phase 5.71 injects the effective CORE
prompts and non-empty Project instructions as subordinate system messages
after AVA's immutable application-owned root prompt. No product root prompt
construction path existed before Phase 5.71; the root is now defined in
`backend/src/ava/services/execution_prompt_context_service.py` and remains
separate from editable CORE definitions. Project instruction persistence still
distinguishes `null` from `""`; execution omits both null and empty/whitespace-only
instruction content. Prompt configuration resolves once at each execution
start, so retries and later runs use current configuration while an active
request keeps its original context. Run-owned inspection snapshots persist the
resolved prompt layers and normalized request used by that run; historical
prompt configuration is never re-resolved for inspection.

Folder and Conversation scopes may affect resolved CORE prompts, but there are
no separate free-form Folder or Conversation instruction fields. The Move
workflow places a conversation in one destination at a time: moving to a Folder
clears Project membership, moving to a Project clears Folder membership, and
Ungrouped clears both. Backend relocation writes both fields atomically.

Canonical data may retain independent Folder and Project fields for existing
assignment and ownership operations; the user-facing Move workflow replaces
both fields atomically and leaves at most one destination set.

Phase 5.79 uses dnd-kit as AVA's shared drag/drop infrastructure. Conversations
can move into a Folder or to Ungrouped, and Folder actions can create a new
conversation directly in that Folder. Relocation clears any previous Project
destination and does not add Folder nesting or manual conversation ordering.

Cross-feature deletion ownership is explicit: Conversation hard delete removes
its owned durable graph and conversation-scoped CORE assignments while its
Folder and Project survive. Folder deletion preserves conversations, clears
their Folder IDs, and preserves independent Project membership and archive
state. Project deletion preserves conversations while clearing Project IDs,
removes Project instructions/defaults and Project-owned file metadata, then
cleans the corresponding binary refs after commit. CORE prompt deletion
removes every assignment for that prompt, including disabled and runtime or
capability scoped assignments. Project File deletion addresses opaque file
identity and content refs, never filenames. Archive remains reversible and
preserves durable content; it is distinct from hard delete.

Phase 5.80 gives archived conversations a dedicated Archived view in the Chat
sidebar. The active sidebar, Folder contents, and active Project conversation
lists exclude archived conversations; global search retains its existing
all-conversations behavior and marks archived results. Archive and Restore
change only the canonical archive flag, preserving Conversation identity,
transcript, run state, pin state, Folder membership, and Project membership.
Restoring returns a conversation to its preserved active location. Archiving
the selected active conversation leaves the sidebar in Active and selects the
next valid active conversation, then the previous one, or no conversation when
none remain. Archived is a separate destination opened intentionally.

Phase 5.83A hardens shared startup recovery. Conversation, Folder, and Document
collection loads distinguish loading, loaded-empty, and failed states; transient
backend failures settle with an explicit retry path, and stale responses cannot
overwrite newer provider generations. Projects and Settings retain independent
load/retry behavior. The Web dev server fails clearly when port 5173 is already
occupied instead of selecting Desktop's port 5174. This recovery adds no backend
schema or data ownership changes.

The Web shell and Desktop package's Vite frontend both project the same
backend-owned durable resources. Native Tauri acceptance was independently
verified on the local X11 desktop: the actual WebView used the same backend
authority as Web, native Chat/Project/Documents/Settings routes loaded, retries
recovered after a backend outage without reloading Tauri, and durable state
reconstructed after development and release-app restarts. A running Tauri
process alone is still not evidence of native acceptance; verify a real window
and interaction when repeating this check on another host.

The certified Phase 5 SQLite schema is version 18, registered as a contiguous,
forward-only migration history at Phase 5 completion. A post-Phase-5 title
ownership migration adds a durable `is_title_custom` marker; automatic title
derivation applies only before the first user message when this marker is false.
Manual rename sets it, and message append persists an untouched conversation's
first-message title without changing that marker. The current SQLite schema is
version 21. Migration 0020 adds nullable run-owned inspection snapshots so
historical execution facts remain stable. Migration 0021 stores an optional
positive context-window token setting per configured model. At execution, AVA
uses that setting, constrained by a provider-reported hard maximum when one is
available. A backend preview uses the same model selector and context policy;
run inspection retains the resulting estimate, input budget, output reserve,
and omitted-history counts. Context estimates are explicitly approximate. The final Phase 5 certification confirms the
durable ownership boundaries and restart/loading behavior above; no schema
migration belongs to Phase 5.85. The complete validation record is
[`docs/AVA_Phase_5_85_Final_Canonical_Validation.md`](docs/AVA_Phase_5_85_Final_Canonical_Validation.md).

`@ava/ui-core` owns AVA's shared design system and the AppearanceProvider used
by both Web and Tauri Desktop. Appearance separates Template, Theme, and Theme
Mode; template and theme identity only affect presentation, never business
behavior. ThemeRegistry and TemplateRegistry allow independent extension, and
templates compose shared feature components rather than duplicate applications.
See [`docs/AVA_UI_1_Design_System_Appearance_Foundation.md`](docs/AVA_UI_1_Design_System_Appearance_Foundation.md).

AVA's shared Button geometry is rounded by default and owned by `@ava/ui-core`.
Lucide React is the canonical icon library for new shared UI. Familiar
contextual actions use the shared icon-first IconButton with a required
accessible name and shared Tooltip behavior. Feature packages consume shared
Button/IconButton primitives rather than defining default geometry or another
icon system; circular controls are intentional exceptions.

AVA dense-list contextual actions use transparent Lucide icon controls at rest,
with rounded invisible hit targets and semantic hover/focus states rather than
persistent filled button chrome.

UI-1 AVA Design System and Appearance Foundation is complete.

AVA uses shared @ava/ui-core semantic themes, Template/Theme/Mode separation, rounded shared buttons, and Lucide icon-first actions across Web/Desktop infrastructure.

Native Tauri Light/Dark/System and appearance persistence are certified.

The `ava-default` template owns the refreshed shared application shell.
Primary navigation is shared between Web and Desktop, and shell actions use
AVA semantic tokens, rounded shared controls, and Lucide icons. Feature
internals remain separate from shell presentation. See
[`docs/AVA_UI_2_Application_Shell_Navigation_Facelift.md`](docs/AVA_UI_2_Application_Shell_Navigation_Facelift.md).

Shell-owned surfaces consume semantic AVA theme tokens across Light, Dark, and
System modes. Primary Dark-mode text uses semantic foreground and renders
light/near-white for readability. Shell controls use shared rounded shadcn/ui
primitives and Lucide icons; execution selectors retain native select behavior
with semantic surface, foreground, border, and focus styling. Legacy feature
internals remain subject to later incremental facelift phases. UI-2A's Web
acceptance passed; native visual acceptance requires an available Tauri window
inspection surface. See
[`docs/AVA_UI_2A_Shell_Theme_Control_Completion.md`](docs/AVA_UI_2A_Shell_Theme_Control_Completion.md).

AVA uses a wide unified rounded Prompt Composer spanning most of the Chat
content width with responsive side margins. Profile, Runtime, Model, and
Workspace remain independent execution settings but are exposed through compact
contextual configuration rather than a permanent four-dropdown grid. The same
shared composer is used by Web and Tauri Desktop. Documents, Projects, Settings
inventory/default cards, and selected sidebar view controls consume active
appearance tokens or their explicit Dark-mode treatment. See
[`docs/AVA_UI_2C_Wide_Unified_Prompt_Composer.md`](docs/AVA_UI_2C_Wide_Unified_Prompt_Composer.md).

In Dark mode, both Active/Archived view controls are black with white labels.
Documents editor actions use gray semantic pills, formatting Undo/Redo use
Lucide icons, toolbar labels use the light foreground, and model capability
checkbox labels resolve through the appearance foreground token.
