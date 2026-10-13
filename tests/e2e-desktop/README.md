# AVA Desktop E2E

These tests launch the actual Tauri desktop binary and drive its WebView with WebdriverIO. They use Tauri's embedded WebDriver provider, so `tauri-driver` and `WebKitWebDriver` are not required.

Run locally with:

```bash
pnpm install
uv sync --project backend
pnpm test:e2e:desktop
```

The runner starts a temporary AVA backend on an available local port with relational persistence in a private SQLite database. Conversation attachment and Project file content use separate temporary storage roots. It builds a debug-only desktop binary pointed at that backend, runs WebdriverIO, then stops the backend and removes all temporary data. It does not use the developer's normal AVA database. On a headless Linux machine, install `xvfb` and run:

```bash
xvfb-run --auto-servernum pnpm test:e2e:desktop
```

The suite seeds clearly disposable conversations, folders, Projects, files, attachments, and a CORE Prompt through the isolated backend fixture. It navigates them through the native UI and creates mock-backed runs through the composer. A test-only backend adapter captures deterministic mock run snapshots so the Inspector can assert the request, prompt layers, response, and attachment context. The embedded WebDriver server and its capability are only enabled for the dedicated debug E2E build. Production Tauri configuration grants only the regular `default` capability.

The Ubuntu GitHub Actions workflow installs the Tauri/WebKit build dependencies and runs this same command under Xvfb.
