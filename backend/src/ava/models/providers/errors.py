"""AVA-owned model provider adapter errors.

Provider adapters translate between AVA contracts and provider SDK/HTTP types.
When a provider fails (transport error, non-success HTTP status, malformed
payload), the adapter raises this AVA-owned error so callers never depend on an
implementation-specific HTTP client exception type. Kept deliberately small: no
deep exception hierarchy in this step.
"""

from __future__ import annotations


class ModelProviderError(Exception):
    """Raised when a model provider adapter cannot fulfill an operation.

    The message is safe for logs and callers: it never includes credentials
    (API keys) or raw request URLs. A non-success HTTP status, when known, is
    preserved in :attr:`status_code` for future callers (e.g. mapping to an
    AVA API error response) without changing the protocol-neutral exception
    type.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code