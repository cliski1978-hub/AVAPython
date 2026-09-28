"""Infrastructure credential backends.

Resolves AVA credential references against real secret storage. The only
backend Phase 5.9 needs is the environment: ``env:NAME`` reads the ``NAME``
environment variable.

This module is deliberately infrastructure-side. A secret backend is a place
where credential material physically exists, so it must not be importable from
core, contracts, models, or services. Keeping the class here also keeps
process-environment access out of the domain, where a persisted
``credential_reference`` has no business reading ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ava.models.credentials import (
    ENVIRONMENT_CREDENTIAL_SCHEME,
    BlankCredentialError,
    CredentialNotFoundError,
    CredentialReference,
    CredentialResolver,
    SecretValue,
    UnsupportedCredentialSchemeError,
)


class EnvironmentCredentialResolver(CredentialResolver):
    """Resolve ``env:NAME`` references from a mapping of environment variables.

    Args:
        environment: Source of environment variables. Defaults to
            :data:`os.environ`. Injectable so tests and a later
            process-scoped snapshot can supply values without mutating the real
            process environment.

    Every failure is deterministic and names only the reference location, never
    the value: an unset variable, a whitespace-only value, a malformed
    reference, and an unsupported scheme are all distinct, catchable outcomes.
    """

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment: Mapping[str, str] = os.environ if environment is None else environment

    def resolve(self, reference: str) -> SecretValue:
        """Resolve ``env:NAME`` to the variable's value.

        Raises:
            CredentialReferenceError: The reference is not shaped
                ``scheme:location``.
            UnsupportedCredentialSchemeError: The scheme is not ``env``.
            CredentialNotFoundError: The variable is not set.
            BlankCredentialError: The variable is set to whitespace only.
        """
        parsed = CredentialReference.parse(reference)
        if parsed.scheme != ENVIRONMENT_CREDENTIAL_SCHEME:
            raise UnsupportedCredentialSchemeError(
                f"Credential scheme is not supported by the environment resolver: {parsed.scheme}"
            )
        name = parsed.location
        if name not in self._environment:
            raise CredentialNotFoundError(f"Credential environment variable is not set: {name}")
        value = self._environment[name]
        if not value.strip():
            raise BlankCredentialError(f"Credential environment variable is blank: {name}")
        return SecretValue(value)
