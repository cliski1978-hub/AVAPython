import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.dirname(fileURLToPath(import.meta.url));
const binaryName = process.platform === "win32" ? "ava-desktop.exe" : "ava-desktop";
const defaultBinary = path.resolve(
  packageRoot,
  `../../frontend/apps/desktop/src-tauri/target/debug/${binaryName}`,
);

/** @type {WebdriverIO.Config} */
export const config = {
  specs: ["./specs/**/*.spec.mjs"],
  maxInstances: 1,
  capabilities: [{ browserName: "tauri" }],
  logLevel: "warn",
  framework: "mocha",
  reporters: ["spec"],
  mochaOpts: {
    timeout: 60_000,
  },
  services: [
    ["tauri", {
      appBinaryPath: process.env.AVA_DESKTOP_BINARY ?? defaultBinary,
      driverProvider: "embedded",
    }],
  ],
};
