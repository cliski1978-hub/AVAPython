"""AVA-owned model provider adapter errors.

Provider adapters translate between AVA contracts and provider SDK/HTTP types.
When a provider fails (transport error, non-success HTTP status, malformed
payload), the adapter raises this AVA-owned error so callers never depend on an
implementation-specific HTTP client exception type.

Protocol interpretation happens *here*, at the adapter boundary: the adapter
decides that a refused connection is a connectivity problem and that a 429 is a
rate limit, and records that decision as an AVA :class:`FailureCode`. Nothing
above this boundary learns an HTTP status, a provider payload shape, or that a
particular vendor exists.
"""

from __future__ import annotations

from ava.contracts.failures import FailureCode


class ModelProviderError(Exception):
    """Raised when a model provider adapter cannot fulfill an operation.

    :attr:`safe_code` is the AVA-owned classification, from the public
    conversation/run failure taxonomy. It is a closed set, so an adapter cannot
    invent a code that no client knows how to present; the runtime and run
    service pass it through unchanged to the durable failure record.

    The message is safe for logs and callers: it never includes credentials
    (API keys), raw request URLs, endpoints, or provider response bodies. A
    non-success HTTP status, when known, is preserved in :attr:`status_code` for
    logs and server-side diagnostics; it is never part of the public payload.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        safe_code: str = FailureCode.PROVIDER_REQUEST_FAILED,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.safe_code = safe_code
