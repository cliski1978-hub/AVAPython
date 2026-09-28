import { ApiError } from "@ava/api-client";
import { describe, expect, it } from "vitest";

import { settingsErrorMessage } from "./settingsErrorMessage";

/**
 * The Settings error contract.
 *
 * These tests exist mainly to pin the second rule: a value that was not a
 * designed `ErrorResponse` must not reach the UI. A single leaked stack frame
 * or internal host name is enough to fail here.
 */

const errorBody = {
  error_code: "unknown_provider_connection",
  category: "not_found",
  message: "Unknown provider connection: acme.",
  recoverable: true,
  details: {},
  correlation_id: null,
  contract_version: "v1" as const,
};

describe("settingsErrorMessage", () => {
  it("shows a backend operator-facing message", () => {
    const message = settingsErrorMessage(
      new ApiError("HTTP 404", 404, errorBody),
    );
    expect(message).toBe("Unknown provider connection: acme.");
  });

  it("explains a 404 with no error envelope", () => {
    const message = settingsErrorMessage(new ApiError("HTTP 404", 404, null));
    expect(message).toMatch(/no longer exists/);
    expect(message).not.toContain("null");
  });

  it("explains a 409 as a conflict", () => {
    const message = settingsErrorMessage(new ApiError("HTTP 409", 409, "<html>"));
    expect(message).toMatch(/conflicts/);
    expect(message).not.toContain("html");
  });

  it("does not blame the server for a 5xx", () => {
    const message = settingsErrorMessage(
      new ApiError("HTTP 500", 500, { traceback: "Traceback (most recent call last)…" }),
    );
    expect(message).toMatch(/server could not complete/);
    expect(message).not.toContain("Traceback");
  });

  it("reports an unreachable backend plainly", () => {
    const message = settingsErrorMessage(new ApiError("network", 0, undefined));
    expect(message).toMatch(/could not be reached/);
  });

  it("falls back to a status sentence for other statuses", () => {
    const message = settingsErrorMessage(new ApiError("HTTP 418", 418, undefined));
    expect(message).toBe("The request failed (HTTP 418).");
  });

  it("never surfaces a thrown message or stack", () => {
    const thrown = new TypeError(
      "Failed to fetch: http://10.0.0.5:8000/settings/providers",
    );
    const message = settingsErrorMessage(thrown);
    expect(message).not.toContain("10.0.0.5");
    expect(message).not.toContain("Failed to fetch");
    expect(message).not.toContain("TypeError");
  });

  it("never surfaces a plain string that may contain detail", () => {
    const message = settingsErrorMessage(
      "sqlite3.OperationalError: no such table: provider_connections",
    );
    expect(message).not.toContain("sqlite3");
    expect(message).not.toContain("no such table");
  });

  it("handles an unreadable response body", () => {
    const message = settingsErrorMessage(new SyntaxError("Unexpected token < in JSON"));
    expect(message).toMatch(/could not read/);
    expect(message).not.toContain("Unexpected token");
  });

  it("handles a null throw", () => {
    expect(settingsErrorMessage(null)).toMatch(/could not load/);
  });
});
