"""Shared AVA contract type utilities.

Defines a recursive JSON-safe value type so all contract fields that carry
arbitrary JSON can enforce serializability at the type level. Provider SDK
objects, datetime objects, bytes, and other non-JSON-safe types are not
permitted.
"""

# PEP 695 named recursive type alias. Requires Python 3.12+.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
