"""Compatibility re-export of the AVA-owned provider error.

This module used to define a second, byte-identical :class:`ModelProviderError`
that nothing imported. Two class objects with the same name are worse than one:
an adapter raising the copy here would not be caught by a handler catching the
canonical type in :mod:`ava.models.errors`, and the failure would silently
collapse to the generic code. It is now a re-export, so both import paths yield
the same class.
"""

from ava.models.errors import ModelProviderError

__all__ = ["ModelProviderError"]
