"""StoredContentInfo/AttachmentContentStore port tests (Step 4.14.B).

Prove the binary physical-content contract:

* ``StoredContentInfo`` is a frozen record carrying exactly ``size_bytes``;
* the content store is an abstract contract declaring exactly
  ``put``/``open``/``exists`` and no delete/remove/list/metadata surface;
* ``put`` takes ``(storage_key, source)`` with a file-like binary source;
* every boundary type is AVA-owned or stdlib — no provider SDK types.

No metadata vocabulary, filesystem logic, configuration, service, or routes
are introduced here (Step 4.14.B scope only).
"""

import sys
from dataclasses import FrozenInstanceError
from dataclasses import fields as dataclass_fields
from inspect import getmembers, signature
from io import BytesIO
from typing import BinaryIO, get_args, get_type_hints

import pytest

from ava.repositories import (
    AttachmentContentStore,
    StoredContentInfo,
)

# ============================================================
# BEGIN: Test double (port shape prove)
# ============================================================


class MemoryAttachmentContentStore(AttachmentContentStore):
    """Framework-free test double used only to prove the port is implementable.

    Mirrors the semantics the real stores will honor: duplicate
    ``storage_key`` raises ``ValueError``, ``open`` on an unknown key raises
    ``FileNotFoundError``, and each call records the same authoritativeness a
    durable provider would. This is a port-shape fake, not the Step 4.14.B
    store.
    """

    def __init__(self) -> None:
        self._contents: dict[str, bytes] = {}

    def put(self, storage_key: str, source: BinaryIO) -> StoredContentInfo:
        if storage_key in self._contents:
            raise ValueError(f"Duplicate storage key: {storage_key}")
        content = source.read()
        self._contents[storage_key] = content
        return StoredContentInfo(size_bytes=len(content))

    def open(self, storage_key: str) -> BinaryIO:
        try:
            return BytesIO(self._contents[storage_key])
        except KeyError:
            raise FileNotFoundError(f"Unknown storage key: {storage_key}") from None

    def exists(self, storage_key: str) -> bool:
        return storage_key in self._contents


# ============================================================
# END: Test double (port shape prove)
# ============================================================


# ============================================================
# BEGIN: StoredContentInfo shape
# ============================================================


def test_stored_content_info_has_exactly_size_bytes_field() -> None:
    """The write result carries exactly one field: the authoritative size."""
    field_names = {field.name for field in dataclass_fields(StoredContentInfo)}
    assert field_names == {"size_bytes"}


def test_stored_content_info_is_immutable() -> None:
    """The write result cannot be mutated after construction."""
    info = StoredContentInfo(size_bytes=42)

    assert info.size_bytes == 42
    with pytest.raises(FrozenInstanceError):
        info.size_bytes = 99  # type: ignore[misc]


def test_stored_content_info_requires_size_bytes() -> None:
    """``size_bytes`` is required to construct the record."""
    with pytest.raises(TypeError):
        StoredContentInfo()  # type: ignore[call-arg]


# ============================================================
# END: StoredContentInfo shape
# ============================================================


# ============================================================
# BEGIN: Abstract contract
# ============================================================


def test_attachment_content_store_is_an_abstract_contract() -> None:
    """The port is a contract, not a usable default implementation."""
    with pytest.raises(TypeError):
        AttachmentContentStore()  # type: ignore[abstract]


def test_port_declares_exactly_three_operations_as_abstract() -> None:
    """All three approved operations are abstract; nothing else is enforced."""
    assert AttachmentContentStore.__abstractmethods__ == frozenset(
        {"put", "open", "exists"}
    )


def test_attachment_content_store_is_implementable_by_fake() -> None:
    """The port surface can be satisfied without any framework or database."""
    store = MemoryAttachmentContentStore()

    result = store.put("attachments/key-1/source", BytesIO(b"hello world"))
    assert result.size_bytes == 11
    assert store.exists("attachments/key-1/source") is True
    assert store.open("attachments/key-1/source").read() == b"hello world"
    assert store.exists("unknown") is False


def test_put_accepts_storage_key_and_streaming_source() -> None:
    """``put`` takes exactly the opaque key and a file-like binary source."""
    parameters = [name for name in signature(AttachmentContentStore.put).parameters if name != "self"]
    assert parameters == ["storage_key", "source"]


# ============================================================
# END: Abstract contract
# ============================================================


# ============================================================
# BEGIN: No delete/metadata surface
# ============================================================


def test_content_port_exposes_delete_but_no_metadata_operations() -> None:
    """Hard-delete cleanup is supported without adding metadata operations."""
    operations = {
        name
        for name, member in getmembers(AttachmentContentStore)
        if not name.startswith("_") and callable(member)
    }
    assert operations == {"put", "open", "exists", "delete"}


# ============================================================
# END: No delete/metadata surface
# ============================================================


# ============================================================
# BEGIN: Return-type conventions
# ============================================================


def test_put_returns_stored_content_info() -> None:
    """``put`` reports the authoritative stored byte count."""
    put_hint = get_type_hints(AttachmentContentStore.put)["return"]
    assert put_hint is StoredContentInfo


def test_open_returns_a_binary_stream() -> None:
    """``open`` returns a readable binary stream, never ``None``."""
    open_hint = get_type_hints(AttachmentContentStore.open)["return"]
    assert open_hint is not type(None)
    root = getattr(open_hint, "__module__", "").split(".")[0]
    assert root in sys.stdlib_module_names or root == "ava"


# ============================================================
# END: Return-type conventions
# ============================================================


# ============================================================
# BEGIN: Boundary type discipline
# ============================================================


def _annotation_root_modules(annotation: object) -> set[str]:
    """Collect top-level module names reachable from a type annotation."""
    modules: set[str] = set()
    pending = [annotation]
    while pending:
        current = pending.pop()
        module = getattr(current, "__module__", None)
        if module:
            modules.add(module.split(".")[0])
        pending.extend(arg for arg in get_args(current) if arg is not current)
    return modules


def test_content_port_uses_only_binary_io_and_string_boundaries() -> None:
    """The port crosses only standard-library/AVA types — no provider SDK types."""
    for method in (AttachmentContentStore.put, AttachmentContentStore.open, AttachmentContentStore.exists):
        for annotation in get_type_hints(method).values():
            for module in _annotation_root_modules(annotation):
                assert module in sys.stdlib_module_names or module == "ava", (
                    AttachmentContentStore.__name__,
                    method.__name__,
                    module,
                )


def test_content_port_never_names_metadata_or_owner_types() -> None:
    """No owner/status/record/file-name/media-type vocabulary crosses the port."""
    for method in (AttachmentContentStore.put, AttachmentContentStore.open, AttachmentContentStore.exists):
        hints = get_type_hints(method)
        joined = " ".join(str(hint) for hint in hints.values())
        for forbidden in ("AttachmentRecord", "AttachmentStatus", "owner", "media_type", "file_name"):
            assert forbidden not in joined, (method.__name__, forbidden)


# ============================================================
# END: Boundary type discipline
# ============================================================


# ============================================================
# BEGIN: Public exports
# ============================================================


def test_content_store_symbols_are_publicly_exported() -> None:
    """Callers reach the record + port through the ``ava.repositories`` barrel."""
    import ava.repositories as repositories
    from ava.repositories import __all__ as repositories_all

    assert "StoredContentInfo" in repositories_all
    assert "AttachmentContentStore" in repositories_all
    assert repositories.StoredContentInfo is StoredContentInfo
    assert repositories.AttachmentContentStore is AttachmentContentStore
    assert repositories.AttachmentContentStore.__abstractmethods__ == frozenset(
        {"put", "open", "exists"}
    )


def test_in_memory_content_store_is_deep_importable_not_in_barrel() -> None:
    """The in-memory adapter follows the store deep-import convention."""
    from ava.repositories import __all__ as repositories_all

    assert "InMemoryAttachmentContentStore" not in repositories_all

    from ava.services.attachment_content_store import InMemoryAttachmentContentStore

    store = InMemoryAttachmentContentStore()
    assert isinstance(store, AttachmentContentStore)


# ============================================================
# END: Public exports
# ============================================================
