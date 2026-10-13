import type { ErrorResponse, JsonValue } from "@ava/contracts";
import { ApiError } from "@ava/api-client";

/** A settings section a failure can point the user at. */
export type FailureSettingsSection = "providers" | "models" | "runtimes" | "defaults";

/**
 * How one conversation failure is presented.
 *
 * `title` is the headline shown beside the failed message, `description` the
 * safe body, and `settingsSection` the place in Settings where the cause lives.
 * `retryable` says whether trying the same request again is worth offering.
 */
export interface FailurePresentation {
  title: string;
  description: string;
  settingsSection?: FailureSettingsSection;
  retryable: boolean;
}

/**
 * The conversation/run failure taxonomy, in one place.
 *
 * Every code the backend can persist on a failed assistant message is listed
 * here with its wording. Keeping this exhaustive is deliberate: a code that
 * falls through to the generic entry would silently lose its specific guidance,
 * which is the behavior this mapping exists to prevent.
 *
 * Codes are the backend's stable strings (`ava.contracts.failures.FailureCode`)
 * and are part of the public contract. Descriptions are AVA's own wording and
 * never contain provider prose, endpoints, or credentials.
 */
const FAILURE_PRESENTATIONS: Record<string, FailurePresentation> = {
  // Configuration
  configuration_missing: {
    title: "Execution configuration missing",
    description:
      "Unable to start this run. The selected execution configuration is incomplete. Choose a valid runtime, model, and provider, then try again.",
    settingsSection: "defaults",
    retryable: false,
  },
  configuration_invalid: {
    title: "Invalid execution configuration",
    description:
      "Unable to start this run. The selected provider, model, and runtime combination is invalid. Review Execution Settings and try again.",
    settingsSection: "defaults",
    retryable: false,
  },
  provider_connection_unavailable: {
    title: "Provider unavailable",
    description:
      "AVA could not reach the configured model provider. Check the provider endpoint or provider availability.",
    settingsSection: "providers",
    retryable: true,
  },
  model_unavailable: {
    title: "Model unavailable",
    description:
      "The configured model could not be found or used by the selected provider. Check the model configuration or choose another model.",
    settingsSection: "models",
    retryable: true,
  },
  runtime_unavailable: {
    title: "Runtime unavailable",
    description: "The selected runtime is not available in this AVA installation.",
    settingsSection: "runtimes",
    retryable: true,
  },
  credential_unavailable: {
    title: "Provider credentials unavailable",
    description:
      "The credentials for the configured provider connection are unavailable. Review the credential reference in Settings.",
    settingsSection: "providers",
    retryable: false,
  },

  // Execution
  provider_request_failed: {
    title: "Model provider request failed",
    description:
      "The configured model provider could not complete the request. Try again or review the provider configuration.",
    settingsSection: "providers",
    retryable: true,
  },
  provider_timeout: {
    title: "Model request timed out",
    description: "The configured provider did not respond in time. Try again or review the provider configuration.",
    settingsSection: "providers",
    retryable: true,
  },
  provider_rate_limited: {
    title: "Provider rate limit reached",
    description:
      "The provider temporarily rejected the request because of usage limits. Try again later or choose another model.",
    retryable: true,
  },
  provider_authentication_failed: {
    title: "Provider authentication failed",
    description: "The provider rejected the configured credentials. Review the provider credential reference in Settings.",
    settingsSection: "providers",
    retryable: false,
  },
  provider_response_invalid: {
    title: "Invalid provider response",
    description: "AVA received a response from the model provider that it could not process.",
    retryable: true,
  },
  runtime_failed: {
    title: "Runtime failed",
    description: "The selected runtime could not complete the request. Try again or choose another runtime.",
    settingsSection: "runtimes",
    retryable: true,
  },
  context_window_exceeded: {
    title: "Conversation too large for this model",
    description:
      "The selected model cannot accept the current conversation context. Reduce the context or choose a model with a larger context window.",
    retryable: false,
  },

  // Interruption: rendered as its own state, never as a failure.
  // Cancellation is normally shown from the message status; this entry is
  // defensive, so a cancellation code on a failed message cannot fall back to
  // "Failed to generate response".
  cancelled: {
    title: "Response stopped",
    description: "The response was stopped before it finished.",
    retryable: true,
  },
  execution_interrupted: {
    title: "Response interrupted",
    description: "The backend restarted before this response finished. You can retry the request.",
    retryable: true,
  },

  // Generic safety net.
  agent_failed: {
    title: "Failed to generate response",
    description: "Something prevented this response from completing.",
    retryable: true,
  },
};

/**
 * The generic presentation, also used for any code outside the taxonomy.
 *
 * A failure always has something truthful to show, so an unrecognized or missing
 * code degrades here rather than rendering an empty error state.
 */
const GENERIC_PRESENTATION: FailurePresentation = FAILURE_PRESENTATIONS.agent_failed;

/** Presentation for a conversation failure code, or the generic fallback. */
export function describeRunFailure(errorCode: string | undefined | null): FailurePresentation {
  if (errorCode == null) return GENERIC_PRESENTATION;
  return FAILURE_PRESENTATIONS[errorCode] ?? GENERIC_PRESENTATION;
}

/** AVA-owned wording for errors whose machine-readable code is known. */
function messageForCode(errorCode: string | undefined): string | null {
  switch (errorCode) {
    case "conversation_attachment_name_conflict":
      return "A file with this name is already attached to this conversation. Remove or rename the existing file before uploading another.";
    case "conversation_run_active":
      return "This conversation already has a response in progress.";
    case "execution_interrupted":
      return "The backend restarted before this response finished.";
    case "cancellation_request_failed":
      return "AVA could not request cancellation. The response may still be running.";
    case "run_not_found":
      return "This response could not be fully restored.";
    default:
      return FAILURE_PRESENTATIONS[errorCode ?? ""]?.description ?? null;
  }
}

/** User-facing, AVA-owned wording for action and transport errors. */
export function presentAvaError(error: unknown, fallback = "That action could not be completed."): string {
  if (error instanceof ApiError) {
    const body = error.body as Partial<ErrorResponse> | null | undefined;
    if (body?.error_code === "conversation_attachment_name_conflict" && body.message) {
      return body.message;
    }
    return messageForCode(body?.error_code) ?? fallback;
  }
  return fallback;
}

/** Maps normalized run failure metadata without exposing provider details. */
export function presentRunFailure(payload: Record<string, JsonValue>): string {
  const errorCode = payload.error_code;
  return describeRunFailure(typeof errorCode === "string" ? errorCode : undefined).description;
}

export function settingsSectionForFailure(errorCode: string | undefined): FailureSettingsSection | undefined {
  return describeRunFailure(errorCode).settingsSection;
}

/** Whether the failed response should offer a retry. */
export function isFailureRetryable(errorCode: string | undefined): boolean {
  return describeRunFailure(errorCode).retryable;
}
