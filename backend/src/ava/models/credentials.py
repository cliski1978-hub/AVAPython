"""AVA-owned credential vocabulary.

``ProviderConnection.credential_reference`` names *where a secret lives*. This
module defines what such a reference means, how it is parsed, what a resolved
secret looks like, and the port that turns a reference into secret material.

Three rules shape everything here:

1. A reference identifies a location, never a secret. Its text is safe to
   persist, log, and return through an API.
2. A resolved secret is wrapped in :class:`SecretValue`, whose ``repr``/``str``
   are redacted so an accidental interpolation cannot leak it.
3. Secrets flow one way: reference -> resolver -> ``SecretValue`` -> provider
   infrastructure. Nothing here is persisted, and nothing here is a public
   contract.

The port is deliberately the smallest useful shape: one ``resolve`` call taking
the opaque reference exactly as stored. Storage-backend detail stays inside the
implementation, so an AWS Secrets Manager or Azure Key Vault backend can be
added later without touching ``ProviderConnection``, this port, or the
provider/model domains.
"""

from __future__ import annotations

import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ava.models.provider_connections import ProviderConnection

#: The only credential-reference scheme Phase 5.9 implements. A reference of
#: the form ``env:NAME`` resolves to the value of the ``NAME`` environment
#: variable. Additional schemes (``aws-secrets:``, ``azure-keyvault:``,
#: ``databricks:``) are recognized as valid reference *syntax* but rejected by
#: this resolver as unsupported, which is what keeps them extensible.
ENVIRONMENT_CREDENTIAL_SCHEME = "env"


# ============================================================
# BEGIN: Errors
# ============================================================


class CredentialError(Exception):
    """Base for every AVA-owned credential failure.

    The message is safe for logs and API responses: it may name the credential
    *reference* (a location, never a secret) but never resolved secret
    material.
    """


class CredentialReferenceError(CredentialError):
    """The reference text is not a well-formed AVA credential reference."""


class UnsupportedCredentialSchemeError(CredentialError):
    """The reference names a valid scheme that this resolver cannot serve."""


class CredentialNotFoundError(CredentialError):
    """The reference resolved to a location that holds no value."""


class BlankCredentialError(CredentialError):
    """The reference resolved to a location holding only whitespace.

    A blank secret is never a usable credential: provider adapters treat a
    blank key as "no authentication configured" (or substitute a local
    placeholder), so a blank value means a misconfiguration rather than a
    deliberate empty credential.
    """


# ============================================================
# END: Errors
# ============================================================


# ============================================================
# BEGIN: Secret Value
# ============================================================


class SecretValue:
    """Resolved secret material, redacted in every string representation.

    Wrapping the secret is what keeps it out of logs, tracebacks, and test
    failure output. ``repr(value)`` renders ``***``, so the only way to obtain
    the plaintext is the explicit :meth:`reveal` call at the provider
    boundary. Deliberately not a dataclass: auto-generated ``__repr__`` and
    ``__eq__`` are exactly the leak paths this class exists to close.
    """

    __slots__ = ("_secret",)

    def __init__(self, secret: str) -> None:
        if not isinstance(secret, str):
            raise TypeError("SecretValue requires a string secret")
        self._secret = secret

    def reveal(self) -> str:
        """Return the plaintext secret.

        The single deliberate exit point for the secret. Callers must be
        provider infrastructure constructing an authenticated client; every
        other layer must handle the ``SecretValue`` itself.
        """
        return self._secret

    def __repr__(self) -> str:
        return f"SecretValue({_REDACTED})"

    def __str__(self) -> str:
        return _REDACTED

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._secret, other._secret)

    def __hash__(self) -> int:
        # Hashing a secret would let it be confirmed by brute force, so a
        # SecretValue is deliberately unhashable.
        raise TypeError("SecretValue is not hashable")

    def __bool__(self) -> bool:
        # A secret's emptiness is a property of the secret, not of the
        # reference. Resolvers reject blank values before wrapping, so this
        # exists only to avoid leaking length or content through truthiness
        # surprises and always reports "there is a value".
        return True


_REDACTED = "***"


# ============================================================
# END: Secret Value
# ============================================================


# ============================================================
# BEGIN: Credential Reference
# ============================================================


@dataclass(frozen=True)
class CredentialReference:
    """A parsed credential reference: a scheme plus a backend-specific location.

    ``env:OPENAI_API_KEY`` parses to scheme ``env`` and location
    ``OPENAI_API_KEY``. The location stays opaque to AVA core: only the
    resolver that owns the scheme interprets it.
    """

    scheme: str
    location: str

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, str) or not self.scheme.strip():
            raise CredentialReferenceError("Credential reference scheme must be a non-blank string")
        if not isinstance(self.location, str) or not self.location.strip():
            raise CredentialReferenceError("Credential reference location must be a non-blank string")

    @classmethod
    def parse(cls, reference: str) -> CredentialReference:
        """Parse reference text, rejecting anything not shaped ``scheme:location``.

        Raises:
            CredentialReferenceError: If the text is blank, carries no scheme
                separator, or has a blank scheme or location. Whether the
                scheme is *supported* is the resolver's decision, not the
                parser's.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise CredentialReferenceError("Credential reference must be a non-blank string")
        scheme, separator, location = reference.strip().partition(":")
        if not separator:
            raise CredentialReferenceError(
                "Credential reference must name a scheme, as in 'env:OPENAI_API_KEY'"
            )
        return cls(scheme=scheme.strip(), location=location.strip())

    def text(self) -> str:
        """Return the canonical reference text, as persisted on a connection."""
        return f"{self.scheme}:{self.location}"


# ============================================================
# END: Credential Reference
# ============================================================


# ============================================================
# BEGIN: Credential Resolver Port
# ============================================================


class CredentialResolver(ABC):
    """Turn an opaque credential reference into secret material.

    Implementations own the storage backend. The port exposes no backend
    detail: a caller supplies the reference string exactly as
    ``ProviderConnection`` stores it and receives a :class:`SecretValue`.
    """

    @abstractmethod
    def resolve(self, reference: str) -> SecretValue:
        """Resolve ``reference`` to secret material.

        Raises:
            CredentialReferenceError: The reference text is malformed.
            UnsupportedCredentialSchemeError: The reference names a scheme this
                resolver does not serve.
            CredentialNotFoundError: The location holds no value.
            BlankCredentialError: The location holds only whitespace.
        """
        raise NotImplementedError


def resolve_connection_credential(
    connection: ProviderConnection, resolver: CredentialResolver
) -> SecretValue | None:
    """Resolve the credential a connection needs, if any.

    Returns ``None`` for a credential-free connection (``credential_reference``
    is ``None``) and never invokes the resolver in that case, so local
    unauthenticated providers stay supported without an environment variable
    and without a resolver call. This is the single seam where a persisted
    connection meets secret material; Phase 5.16 uses it to hand a secret to
    provider construction.
    """
    if connection.credential_reference is None:
        return None
    return resolver.resolve(connection.credential_reference)


# ============================================================
# END: Credential Resolver Port
# ============================================================
