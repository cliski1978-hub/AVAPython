import { ApiError } from "@ava/api-client";
import type { ErrorResponse } from "@ava/contracts";

/**
 * Maps a transport failure to a message that is safe to show a user.
 *
 * Two rules, both deliberate:
 *
 *  1. A backend `ErrorResponse` message is shown, because the Settings API
 *     already returns an operator-facing sentence (Phase 5.10 returns e.g.
 *     "Unknown provider connection: acme"). It is a designed UI string, not a
 *     diagnostic.
 *  2. Anything else is reduced to a fixed sentence. A raw thrown value can
 *     contain a stack trace, an internal URL, a driver message, or — if a
 *     future caller passes something careless — request detail. None of that
 *     belongs in Settings chrome.
 *
 * The status is used only to choose a category, never to echo itself blindly.
 */

/** A backend `ErrorResponse` body, or anything else. */
function isErrorResponse(body: unknown): body is ErrorResponse {
  if (body == null || typeof body !== "object") return false;
  const candidate = body as Partial<ErrorResponse>;
  return (
    typeof candidate.message === "string" &&
    typeof candidate.error_code === "string"
  );
}

export function settingsErrorMessage(
  error: unknown,
  fallback = "AVA could not load this configuration. Try again.",
): string {
  if (error instanceof ApiError) {
    if (isErrorResponse(error.body)) {
      return error.body.message;
    }

    if (error.status === 404) {
      return "That configuration record no longer exists. Reload to see the current configuration.";
    }
    if (error.status === 409) {
      return "That change conflicts with the current configuration. Reload and try again.";
    }
    if (error.status >= 500) {
      return "The server could not complete that request. Try again in a moment.";
    }
    if (error.status === 0) {
      return "AVA could not be reached. Check that the backend is running.";
    }

    return `The request failed (HTTP ${error.status}).`;
  }

  if (error instanceof SyntaxError) {
    return "The server returned a response AVA could not read.";
  }

  // Network failure, abort, or an unexpected value: no detail, no stack. The
  // caller supplies the final sentence, since loading and saving want to read
  // differently.
  return fallback;
}
