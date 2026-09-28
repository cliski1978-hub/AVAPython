import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Phase 5.11 frontend boundaries, narrowed by Phases 5.12-5.14.
 *
 * Three kinds of guard live here.
 *
 * Transport and safety boundaries, which hold for every future phase: the
 * Settings surface reaches the backend only through `@ava/api-client`, and no
 * secret concept may enter a frontend contract, state, or view.
 *
 * Phase-boundary guards, which hold only until the management phases. These
 * encode what each phase has *not* yet opened, so 5.12-5.14 each have to relax a
 * specific assertion when they deliberately add a write. That is intentional: a
 * boundary that is never lifted cannot tell anyone anything.
 *
 * 5.12 lifted provider writes, 5.13 lifted model writes, and 5.14 lifted runtime
 * writes. The remaining list is a single entry wide, so the guard still fails if
 * defaults editing is ever reached for ahead of 5.15.
 */

const root = join(import.meta.dirname, "..");
const packageRoot = join(root, "src");

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? files(join(directory, entry.name))
      : entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")
        ? [join(directory, entry.name)]
        : [],
  );
}

function sources(): string[] {
  return files(packageRoot).filter(
    (file) => !file.endsWith("settings.architecture.test.ts"),
  );
}

/** Shipped code, excluding tests, for guards whose subject words appear in tests. */
function featureSources(): string[] {
  return sources().filter((file) => !/\.test\.tsx?$/.test(file));
}

const SECRET_VOCABULARY = [
  "SecretValue",
  "resolveCredential",
  "resolveConnectionCredential",
  "api_key",
  "apiKey",
  "secretValue",
];

describe("Settings transport and safety boundaries", () => {
  it("never calls fetch directly", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/fetch\s*\(/);
    }
  });

  it("reaches the backend only through the shared API client", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/XMLHttpRequest|axios|EventSource|WebSocket/);
    }
  });

  it("introduces no secret material concept", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      for (const token of SECRET_VOCABULARY) {
        expect(text, `${file}: ${token}`).not.toContain(token);
      }
    }
  });

  it("does not persist anything to browser storage", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      for (const token of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) {
        expect(text, `${file}: ${token}`).not.toContain(token);
      }
    }
  });

  it("imports no second state-management library", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      for (const token of ["redux", "zustand", "mobx", "jotai", "recoil", "valtio"]) {
        expect(text, `${file}: ${token}`).not.toMatch(
          new RegExp(`from ["']${token}`, "i"),
        );
      }
    }
  });

  it("depends only on shared AVA packages and react", () => {
    const manifest = JSON.parse(
      readFileSync(join(root, "package.json"), "utf8"),
    ) as {
      dependencies: Record<string, string>;
      peerDependencies: Record<string, string>;
    };
    // `typescript` is a build-time peer like react; it pulls no runtime code.
    const allowed = /^(react|react-dom|typescript|@ava\/)/;
    for (const name of Object.keys({
      ...manifest.dependencies,
      ...manifest.peerDependencies,
    })) {
      expect(allowed.test(name), name).toBe(true);
    }
  });
});

describe("Phase 5.15 boundary: the Settings surface is complete", () => {
  /**
   * Phase 5.12 opened provider-connection management, 5.13 model management,
   * 5.14 runtime management, and 5.15 execution defaults. Each removed exactly
   * its own entries and nothing else.
   *
   * There is no later phase in Phase 5, so the "not yet opened" list is empty
   * and the boundary changes shape: rather than forbidding a named write, the
   * guard now pins the *exact* set of writes the Settings surface may perform.
   * That is the stronger statement, and it is what stops a future phase from
   * quietly adding an eighth write — or from reusing a removed phase's entry.
   */
  const SETTINGS_WRITES = [
    "createProviderConnection",
    "updateProviderConnection",
    "createModelConfiguration",
    "updateModelConfiguration",
    "createRuntimeConfiguration",
    "updateRuntimeConfiguration",
    "setExecutionDefaults",
  ];

  /**
   * Every wrapper the API client exports, read from the real modules.
   *
   * The Settings surface legitimately reaches past `settings.ts`: 5.12-5.14
   * read `/model-providers` and `/runtimes` for adapter-type and registry
   * choices. So the exported set spans the whole client, while the write set
   * below is still confined to `settings.ts` — that separation is the boundary.
   */
  function apiExports(): string[] {
    const clientRoot = join(packageRoot, "..", "..", "api-client", "src");
    const names: string[] = [];
    for (const entry of readdirSync(clientRoot)) {
      if (!entry.endsWith(".ts") || entry.endsWith(".test.ts")) {
        continue;
      }
      const source = readFileSync(join(clientRoot, entry), "utf8");
      names.push(
        ...[...source.matchAll(/export async function (\w+)/g)].map(
          (match) => match[1],
        ),
      );
    }
    return names;
  }

  /** The writes the Settings module itself owns. */
  function settingsWriteExports(): string[] {
    const source = readFileSync(
      join(packageRoot, "..", "..", "api-client", "src", "settings.ts"),
      "utf8",
    );
    return [...source.matchAll(/export async function (\w+)/g)]
      .map((match) => match[1])
      .filter((name) => !/^(list|get)[A-Z]/.test(name))
      .sort();
  }

  it("confirms the Settings API exposes exactly these seven writes", () => {
    // The truth is derived from the API module rather than restated here, so
    // this fails if a write is added on either side without the other. It also
    // documents that the API has no delete: retirement is done by disabling.
    const writes = settingsWriteExports();
    expect(writes).toEqual([...SETTINGS_WRITES].sort());
    expect(
      writes.some((name) => /delete|remove/i.test(name)),
      "the Settings API must not expose a delete or remove",
    ).toBe(false);
  });

  it("reaches every Settings write and no other wrapper", () => {
    const used = new Set<string>();
    for (const file of featureSources()) {
      const text = readFileSync(file, "utf8");
      for (const name of apiExports()) {
        if (text.includes(name)) {
          used.add(name);
        }
      }
    }
    const writesUsed = [...used]
      .filter((name) => !/^(list|get)[A-Z]/.test(name))
      .sort();
    expect(writesUsed).toEqual([...SETTINGS_WRITES].sort());
  });

  it("invokes no wrapper that the Settings API does not export", () => {
    // A wrapper reached by name but absent from the API would be a stale or
    // invented call, so the imported names are checked against the real module
    // rather than only against a hardcoded list.
    const exported = new Set(apiExports());
    for (const file of featureSources()) {
      const text = readFileSync(file, "utf8");
      const importBlock = text.match(
        /import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*["']@ava\/api-client["']/g,
      );
      for (const block of importBlock ?? []) {
        for (const raw of block.matchAll(/\b(list|get|create|update|set|delete)[A-Z]\w*/g)) {
          expect(exported.has(raw[0]), `${file}: ${raw[0]}`).toBe(true);
        }
      }
    }
  });

  it("builds default-selector sources only from the Settings module", () => {
    /**
     * The defaults editor is the one place that could plausibly reach for
     * discovery: it needs "a model" and "a runtime" and the obvious-looking
     * endpoints are `/models` and `/runtimes`. It must not.
     *
     * `/model-providers`, `/models`, and `/runtimes` report what the *host*
     * happens to support. `/settings/*` reports what the operator has
     * *configured*. A default is a persisted reference, and 5.8 validates it
     * against configured records — so sourcing a default id from discovery
     * would produce a value the API rejects, or worse, one that happens to be
     * accepted and silently means something else.
     *
     * 5.12-5.14 legitimately use the discovery endpoints for adapter-type and
     * registry *labels*. So the test is scoped to the defaults surface, where
     * the selector ids are chosen.
     */
    const source = readFileSync(
      join(packageRoot, "defaults", "ExecutionDefaultsEditor.tsx"),
      "utf8",
    );
    for (const discovery of ["getModelProviders", "getRuntimes", "listModels"]) {
      expect(source, discovery).not.toContain(discovery);
    }
    // The three configured inventories are the whole source set.
    for (const configured of [
      "listProviderConnections",
      "listModelConfigurations",
      "listRuntimeConfigurations",
    ]) {
      expect(
        readFileSync(
          join(packageRoot, "sections", "ExecutionDefaultsSection.tsx"),
          "utf8",
        ),
        configured,
      ).toContain(configured);
    }
  });

  it("issues no non-GET request from the settings surface", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      // Every write goes through the shared client wrappers, which own the HTTP
      // verb. The settings surface still never spells one out.
      expect(text, file).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)["']/);
    }
  });

  it("does not render an enable/disable mutation control", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      // A label may describe state ("Disabled"); it may not be an action.
      // Enabled is a field of the edit form, not a row-level toggle.
      expect(text, file).not.toMatch(/(onClick|onChange)[^>]{0,120}["'](Enable|Disable)["']/);
    }
  });

  it("offers no delete or remove action for a settings record", () => {
    // Spans all three configured records, including the runtime configuration
    // added in 5.14: retiring a record is done by disabling it, so it stays
    // findable and re-enablable.
    // Feature sources only: the test files deliberately spell these words out
    // to assert their absence.
    for (const file of featureSources()) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(
        /(delete|remove)(ProviderConnection|ModelConfiguration|RuntimeConfiguration)\w*|["'](Delete|Remove)\b/,
      );
    }
  });

  it("reaches writes only through the shared API client", () => {
    // The typed wrappers own both the HTTP verb and the payload shape, so the
    // surface itself never builds a request. Checked on call syntax rather than
    // on route strings, which appear in prose comments legitimately.
    for (const file of featureSources()) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(
        /client\.request\(|new\s+(WebSocket|EventSource)\(|XMLHttpRequest|[^.\w]fetch\(/,
      );
    }
  });
  it("renders exactly the declared capability vocabulary", () => {
    // The model form offers the capability flags the contract declares, as a
    // fixed list. This cross-checks the two files, so a flag added to (or
    // removed from) `ModelCapabilities` cannot leave the UI silently rendering a
    // stale set, and so the UI cannot invent a flag the backend would reject.
    const contracts = readFileSync(
      join(packageRoot, "..", "..", "contracts", "src", "models.ts"),
      "utf8",
    );
    const block = contracts.match(/export interface ModelCapabilities \{([^}]*)\}/)?.[1];
    expect(block, "ModelCapabilities not found in the contracts package").toBeDefined();

    const declared = [...(block ?? "").matchAll(/^  (\w+): boolean;/gm)].map(
      (match) => match[1],
    );
    expect(declared.length).toBeGreaterThan(0);

    const ui = readFileSync(
      join(packageRoot, "models", "modelCapabilities.ts"),
      "utf8",
    );
    const rendered = [...ui.matchAll(/\{ key: "(\w+)"/g)].map((match) => match[1]);
    expect(rendered.sort()).toEqual([...declared].sort());
  });
});
