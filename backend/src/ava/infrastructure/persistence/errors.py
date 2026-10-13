"""Persistence error boundary (Step 4.6).

Database failures that cannot be expressed by repository-port semantics are
raised here so application services and API routes never observe raw driver
exceptions, table names, or connection strings. Duplicate-key violations are
translated to the port's ``ValueError``; every other failure surfaces as
``PersistenceError``.
"""


class PersistenceError(RuntimeError):
    """A database-level failure that no repository-port method can express natively."""
