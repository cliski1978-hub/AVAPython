"""The public conversation/run failure taxonomy.

One vocabulary, owned here, that every layer classifies into: provider adapters
interpret protocol conditions, runtimes and agents preserve a classification,
and the run service normalizes it into the durable ``run_failed`` payload. A
code is chosen once and travels unchanged to the public event, to the assistant
message record, and to the frontend presentation map.

This module deliberately holds *only* the public classification: a stable code,
a safe message, and whether a retry can help. It holds no raw provider payload,
no exception text, and no diagnostic detail. Anything more specific belongs in
the server log, which is why :class:`FailureCode` is a closed set rather than a
free-form string: an unknown code cannot be invented on the way out, so the
generic :attr:`FailureCode.AGENT_FAILED` fallback always remains reachable.

Layering rules that keep the taxonomy honest:

- Provider adapters own HTTP/protocol interpretation. A 404, a 429, or a refused
  connection becomes an AVA code at that boundary and nowhere else, so no service
  ever learns that Ollama exists.
- Runtimes and agents preserve a code they were given. They may classify their
  *own* layer (a context window that cannot fit, an incompatible combination),
  but they never widen a specific code into ``agent_failed``.
- The run service is the only place a public failure payload is built.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeGuard

from ava.contracts.json_types import JsonValue


class FailureCode(StrEnum):
    """Stable public failure codes.

    These strings are a wire contract: the frontend maps them to presentation,
    and a rename is a breaking change for any client holding a persisted
    conversation. Existing codes keep their names and meanings.
    """

    # -- Configuration: AVA cannot execute with what it is configured to use.
    CONFIGURATION_MISSING = "configuration_missing"
    CONFIGURATION_INVALID = "configuration_invalid"
    PROVIDER_CONNECTION_UNAVAILABLE = "provider_connection_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"

    # -- Execution: the configuration resolved, and the work then failed.
    PROVIDER_REQUEST_FAILED = "provider_request_failed"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_AUTHENTICATION_FAILED = "provider_authentication_failed"
    PROVIDER_RESPONSE_INVALID = "provider_response_invalid"
    RUNTIME_FAILED = "runtime_failed"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"

    # -- Interruption: not an error, and never presented as one.
    CANCELLED = "cancelled"
    EXECUTION_INTERRUPTED = "execution_interrupted"

    # -- Generic: the safety net for anything not classified above.
    AGENT_FAILED = "agent_failed"


#: Safe, user-facing wording per code. These strings are part of the public
#: contract and are shown verbatim in the conversation UI. They name the problem
#: and the next step; they never carry provider prose, hostnames, endpoints,
#: credential references, or payload fragments.
PUBLIC_FAILURE_MESSAGES: dict[str, str] = {
    FailureCode.CONFIGURATION_MISSING: (
        "AVA does not have a complete execution configuration. Choose a runtime, model, and provider in Settings."
    ),
    FailureCode.CONFIGURATION_INVALID: (
        "The selected provider, model, and runtime combination cannot be used. Review the execution settings."
    ),
    FailureCode.PROVIDER_CONNECTION_UNAVAILABLE: (
        "AVA could not reach the configured model provider. Check the provider endpoint or provider availability."
    ),
    FailureCode.MODEL_UNAVAILABLE: (
        "The configured model could not be found or used by the selected provider. "
        "Check the model configuration or choose another model."
    ),
    FailureCode.RUNTIME_UNAVAILABLE: (
        "The selected runtime is not available in this AVA installation. Choose another runtime in Settings."
    ),
    FailureCode.CREDENTIAL_UNAVAILABLE: (
        "The credentials for the configured provider connection are unavailable. "
        "Review the credential reference in Settings."
    ),
    FailureCode.PROVIDER_REQUEST_FAILED: (
        "The configured model provider could not complete the request. Try again or review the provider configuration."
    ),
    FailureCode.PROVIDER_TIMEOUT: (
        "The configured provider did not respond in time. Try again or review the provider configuration."
    ),
    FailureCode.PROVIDER_RATE_LIMITED: (
        "The provider temporarily rejected the request because of usage limits. "
        "Try again later or choose another model."
    ),
    FailureCode.PROVIDER_AUTHENTICATION_FAILED: (
        "The provider rejected the configured credentials. Review the provider credential reference in Settings."
    ),
    FailureCode.PROVIDER_RESPONSE_INVALID: (
        "AVA received a response from the model provider that it could not process."
    ),
    FailureCode.RUNTIME_FAILED: (
        "The selected runtime could not complete the request. Try again or choose another runtime."
    ),
    FailureCode.CONTEXT_WINDOW_EXCEEDED: (
        "The selected model cannot accept the current conversation context. "
        "Reduce the context or choose a model with a larger context window."
    ),
    FailureCode.CANCELLED: "The response was stopped before it finished.",
    FailureCode.EXECUTION_INTERRUPTED: (
        "The backend restarted before this response finished. You can retry the request."
    ),
    FailureCode.AGENT_FAILED: "Something prevented this response from completing.",
}

#: Whether retrying the same request could plausibly succeed. Configuration and
#: incompatibility codes are excluded: they need a user change first, and
#: ``agent_failed`` keeps the historical non-recoverable meaning.
NON_RECOVERABLE_CODES: frozenset[str] = frozenset(
    {
        FailureCode.CONFIGURATION_MISSING,
        FailureCode.CONFIGURATION_INVALID,
        FailureCode.CREDENTIAL_UNAVAILABLE,
        # A rejected credential needs a Settings change, exactly like a credential
        # AVA could not resolve, so the two agree on recoverability.
        FailureCode.PROVIDER_AUTHENTICATION_FAILED,
        FailureCode.AGENT_FAILED,
    }
)


def is_known_failure_code(code: object) -> TypeGuard[str]:
    """Whether ``code`` is part of the public taxonomy."""
    return isinstance(code, str) and code in PUBLIC_FAILURE_MESSAGES


def failure_message(code: object, fallback: str | None = None) -> str:
    """The safe public message for ``code``.

    An unknown code degrades to the generic message rather than echoing the
    code or anything a caller passed in, so a stray internal string can never
    reach the public payload.
    """
    if is_known_failure_code(code):
        return PUBLIC_FAILURE_MESSAGES[code]
    return PUBLIC_FAILURE_MESSAGES[FailureCode.AGENT_FAILED] if fallback is None else fallback


def failure_recoverable(code: object) -> bool:
    """Whether ``code`` is recoverable, defaulting unknown codes to generic."""
    if not is_known_failure_code(code):
        return False
    return code not in NON_RECOVERABLE_CODES


def failure_payload(code: object, *, recoverable: bool | None = None) -> dict[str, JsonValue]:
    """Build the durable public payload for a failure.

    ``code`` is coerced to the generic code when unknown, which is what keeps
    the generic fallback reachable no matter what an inner layer passes up.
    """
    resolved = code if is_known_failure_code(code) else FailureCode.AGENT_FAILED
    return {
        "error_code": str(resolved),
        "message": PUBLIC_FAILURE_MESSAGES[str(resolved)],
        "recoverable": failure_recoverable(resolved) if recoverable is None else recoverable,
    }
