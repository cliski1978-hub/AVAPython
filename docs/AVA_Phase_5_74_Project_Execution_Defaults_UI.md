# Phase 5.74 — Project Execution Defaults UI

**Status: COMPLETE**

Phase 5.74 adds Project-scoped runtime and model default controls under
`Project → Settings → Execution Defaults`. It consumes the existing typed
Project execution-default API and runtime/model configuration reads. No backend,
API-client, execution-selector, or resolver behavior changed.

## Behavior

- Preferred Runtime is populated from runtime discovery and stores the
  canonical runtime registry key.
- Preferred Model is populated from enabled configured models and stores the
  stable AVA `model_id`. Labels include the configured display name and
  provider-connection label when available; provider-native model names and
  provider/connection IDs are not sent as Project defaults.
- Both controls use **Use application default** for a stored null. Runtime and
  model are edited independently and the UI shows the existing per-axis
  precedence as informational text only.
- A save sends only fields changed from the persisted Project values. Clearing
  one field sends an explicit null for that field alone; clearing both is
  available through **Use application defaults**.
- Save failures retain the draft, show a localized message, clear pending
  state, and allow retry. Validation failures refresh the available choices.
- An unavailable runtime and a removed/disabled stored model are preserved in
  the editor with a warning and a safe clear/reselect path; no replacement is
  silently chosen.
- Cancel restores the latest persisted values. Refresh updates a clean editor
  and leaves a dirty draft intact. Settings content is keyed by Project ID, so
  switching Projects discards the old Project's unsaved local draft. Archived
  Projects remain editable.

The editor does not calculate effective selection, alter precedence, edit
application defaults, expose provider defaults, add per-run overrides, or
change Project Instructions / System Prompts behavior.

## Validation

`ProjectExecutionDefaultsEditor.test.tsx` covers null, one-axis, and two-axis
rendering; runtime-only and model-only updates; explicit null clears; clear
both; stale runtime and disabled model states; save failure and duplicate save;
and clean/dirty refresh behavior. `ProjectsWorkspace.test.tsx` covers discovery
under Settings while retaining System Prompts and confirms archived Project
editability. The runtime-only request assertion is the load-bearing regression
for omitted-vs-null behavior: temporarily adding the unchanged model field to
runtime-only updates caused 3 tests to fail; the mutation was reverted and the
suite passed again. No live persistence or mixed-source run validation was
available because the local web/API endpoints were not running; those checks
remain dependent on a running local API and configured runtime/model.

Validation results:

- Workspace suite: **164 passed, 6 skipped**.
- API-client suite: **110 passed**.
- TypeScript checks: `@ava/workspace`, `@ava/api-client`, `@ava/contracts`,
  and `@ava/settings-core` passed.
- Web and Desktop production builds passed. Vite reported the existing
  large-chunk advisory (the generated JavaScript bundle is about 734 kB).
- `git diff --check` passed.
- Live persistence, mixed-source run selection, clear/fallback, and explicit
  override checks were not run: neither local port 5174 nor 8000 was reachable.
