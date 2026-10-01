import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Desktop acceptance harness.
 *
 * These tests render the real Desktop shell, so the environment must match the
 * shipped one: the same React plugin, and a browser-like DOM for the shared
 * workspace components. Nothing Desktop-specific is configured here beyond
 * that — if a test needs a Desktop behaviour, it belongs in a shared package.
 */
export default defineConfig({
  plugins: [react()],
  envDir: "../../..",
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
