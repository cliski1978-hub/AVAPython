import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, rm, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const backendRoot = path.join(repoRoot, "backend");
const e2eBackendRoot = path.join(repoRoot, "tests", "e2e-desktop");
const venvUvicorn = process.platform === "win32"
  ? path.join(backendRoot, ".venv", "Scripts", "uvicorn.exe")
  : path.join(backendRoot, ".venv", "bin", "uvicorn");
const temporaryData = await mkdtemp(path.join(os.tmpdir(), "ava-desktop-e2e-"));
let backend;

function pnpmCommand() {
  return process.platform === "win32" ? "pnpm.cmd" : "pnpm";
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      stdio: "inherit",
      env: process.env,
      shell: process.platform === "win32",
      ...options,
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with ${signal ?? code}`));
    });
  });
}

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (address == null || typeof address === "string") throw new Error("Could not reserve a local backend port.");
  const { port } = address;
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForBackend(url) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (backend?.exitCode != null) throw new Error("The isolated AVA backend stopped before it became ready.");
    try {
      const response = await fetch(`${url}/health`);
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error("Timed out waiting for the isolated AVA backend health endpoint.");
}

async function stopBackend() {
  if (backend == null || backend.exitCode != null) return;
  backend.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => backend.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (backend.exitCode == null) backend.kill("SIGKILL");
}

function hasUsableXDisplay() {
  if (process.platform !== "linux" || !process.env.DISPLAY) return false;
  return spawnSync("xdpyinfo", ["-display", process.env.DISPLAY], { stdio: "ignore" }).status === 0;
}

function hasXvfbRunner() {
  return spawnSync("xvfb-run", ["--help"], { stdio: "ignore" }).error == null;
}

try {
  const useXvfb = process.platform === "linux" && !hasUsableXDisplay();
  if (useXvfb && !hasXvfbRunner()) {
    throw new Error("No usable X display was found. Install xvfb and run `xvfb-run --auto-servernum pnpm test:e2e:desktop`.");
  }

  try {
    await stat(venvUvicorn);
  } catch {
    throw new Error(`Backend venv not found at ${venvUvicorn}. Run the backend dependency sync before desktop E2E.`);
  }

  const port = await freePort();
  const apiUrl = `http://127.0.0.1:${port}`;
  backend = spawn(venvUvicorn, [
    "e2e_backend:create_app",
    "--factory",
    "--host", "127.0.0.1",
    "--port", String(port),
    "--log-level", "warning",
  ], {
    cwd: backendRoot,
    stdio: "inherit",
    env: {
      ...process.env,
      AVA_HOST: "127.0.0.1",
      AVA_PORT: String(port),
      AVA_AGENT_PROVIDER: "mock",
      AVA_PERSISTENCE: "relational",
      AVA_PERSISTENCE_DATABASE_URL: path.join(temporaryData, "ava.sqlite3"),
      AVA_ATTACHMENT_STORAGE: "local",
      AVA_ATTACHMENT_STORAGE_ROOT: path.join(temporaryData, "attachments"),
      AVA_PROJECT_FILE_STORAGE: "local",
      AVA_PROJECT_FILE_STORAGE_ROOT: path.join(temporaryData, "project-files"),
      PYTHONPATH: [path.join(backendRoot, "src"), e2eBackendRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    },
  });
  await waitForBackend(apiUrl);

  const testEnvironment = { ...process.env, VITE_API_BASE_URL: apiUrl, AVA_TEST_API_URL: apiUrl };
  await run(pnpmCommand(), [
    "--filter", "@ava/desktop", "tauri", "build", "--debug", "--no-bundle",
    "--features", "wdio", "--config", "src-tauri/tauri.e2e.conf.json",
  ], { env: testEnvironment });

  const testCommand = useXvfb
    ? "xvfb-run"
    : pnpmCommand();
  const testArgs = testCommand === "xvfb-run"
    ? ["--auto-servernum", pnpmCommand(), "--filter", "@ava/e2e-desktop", "test:wdio"]
    : ["--filter", "@ava/e2e-desktop", "test:wdio"];
  await run(testCommand, testArgs, { env: testEnvironment });
} finally {
  await stopBackend();
  await rm(temporaryData, { recursive: true, force: true });
}
