# #48 Frontend Package Validation

**Status: PASS.** Shared model-configuration contracts now match the backend, the reported test defects are corrected, all frontend tests pass with only the existing integration skips, all package typechecks pass, and both app frontend builds succeed.

## Environment and workspace

- Repository: `/home/bizon/AvaUi`
- Node.js `v24.21.0`; pnpm `12.4.1`
- Workspace packages: `@ava/contracts`, `@ava/api-client`, `@ava/ui-core`, `@ava/agent-ui`, `@ava/document-core`, `@ava/settings-core`, `@ava/workspace`, `@ava/web`, `@ava/desktop`, and `@ava/mobile`.
- `tests/e2e-desktop` is excluded from the aggregate unit-test command. Native Tauri E2E is separate from this frontend package/build gate.

## Fixes made

1. **Model context-window contract:** the backend response always includes `context_window_tokens` as `int | None`; create and update request fields are optional nullable integers. Added the required `number | null` response field and optional `number | null` create field to `@ava/contracts`. Update already had the correct optional nullable type. The API client wrappers already pass JSON bodies and responses through unchanged, so no transport implementation change was needed. Added an API-client test that verifies a numeric create payload is serialized and numeric/null responses deserialize as expected.
2. **Project-switch fixture:** changed the delayed Project conversation responses to complete `ConversationListResponse` values, deriving the response type from `listProjectConversations`. Assertions and runtime behavior are unchanged.
3. **Run Inspector resize test:** product code declares and enforces the 280–700px range. jsdom did not provide native `PointerEvent` fields, so the previous drag events had no pressed-button state and the handler correctly ignored them. Added a PointerEvent-compatible test polyfill and verified below-minimum, in-range, and above-maximum drags, including persisted widths. No product resize behavior changed.
4. **Transport recovery test:** the test left the prompt-preview request unmocked while using an intentionally invalid API host, so that expected fixture failure changed the app status to Unavailable before the recovery sequence. The test now mocks model discovery and prompt preview, clears local and session storage between cases, resolves its initial health response explicitly, and then exercises failure and successful recovery through separate `ApiClient` instances. No arbitrary delay or production connectivity change was added.
5. **Settings fixture typing:** added the now-required nullable context-window value to the shared Settings model fixture.

## Focused validation

- `pnpm --filter @ava/contracts test` and `pnpm --filter @ava/contracts lint` — **42 tests passed**, typecheck passed.
- `pnpm --filter @ava/api-client exec vitest run src/settings.test.ts` — **8 tests passed**, including context-window serialization/deserialization. Full API-client suite — **116 tests passed**.
- `pnpm --filter @ava/settings-core test` and `pnpm --filter @ava/settings-core lint` — **213 tests passed**, typecheck passed.
- `pnpm --filter @ava/workspace exec vitest run src/AppWorkspace.test.tsx` — **44 tests passed**, including Inspector width bounds and transport failure/recovery.
- `pnpm --filter @ava/workspace exec vitest run src/ProjectsWorkspace.test.tsx -t 'ignores late Project A conversation references'` — **1 test passed**.
- Workspace typecheck passed.

## Full validation commands and results

```bash
pnpm test
pnpm --filter @ava/desktop test
pnpm lint
pnpm --filter @ava/agent-ui lint
pnpm --filter @ava/workspace lint
pnpm --filter @ava/web lint
pnpm --filter @ava/desktop lint
pnpm --filter @ava/mobile lint
pnpm --filter @ava/web build
pnpm --filter @ava/desktop build
```

The aggregate `pnpm test` run recorded **1,112 passed, 0 failed, 6 skipped** across the frontend packages. The Desktop package was also independently rerun: **11 passed**. The six aggregate skips are the existing live-backend integration cases in two workspace test files; no tests were disabled or weakened for this validation.

| Package | Tests | Lint/typecheck | Build |
|---|---:|---|---|
| `@ava/contracts` | PASS — 42 | PASS | n/a |
| `@ava/api-client` | PASS — 116 | PASS | n/a |
| `@ava/ui-core` | PASS — 78 | PASS | n/a |
| `@ava/agent-ui` | PASS — 316 | PASS | n/a |
| `@ava/document-core` | PASS — 70 | PASS | n/a |
| `@ava/settings-core` | PASS — 213 | PASS | n/a |
| `@ava/workspace` | PASS — 266; 6 integration skips | PASS | n/a |
| `@ava/web` | no test script | PASS | PASS |
| `@ava/desktop` | PASS — 11 | PASS | PASS |
| `@ava/mobile` | no test script | PASS | no build script |

Both Vite builds emitted the existing non-failing large-chunk advisory (the main JS chunk is about 1.05 MB minified). No build or typecheck errors remain. The previous Settings contract errors, Project fixture error, resize assertion failure, and transport-recovery assertion failure are resolved.

## Files changed

- `frontend/packages/contracts/src/settings.ts`
- `frontend/packages/api-client/src/settings.test.ts`
- `frontend/packages/settings-core/src/defaults/defaultChoices.test.ts`
- `frontend/packages/workspace/src/ProjectsWorkspace.test.tsx`
- `frontend/packages/workspace/src/AppWorkspace.test.tsx`
- `docs/test-results/48-frontend-package-validation.md`

## Final status

**#48 Frontend Package Validation — PASS.** No unresolved frontend validation failures or Phase 5 regressions remain.
