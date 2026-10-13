"""LocalAttachmentContentStore behavior tests (Step 4.14.D).

Prove the first physical content adapter on the ``AttachmentContentStore``
port:

* an explicit storage root is required; a missing root is created (parents
  included) and a root that exists but is not a directory fails clearly;
* ``storage_key`` stays a logical reference: absolute keys, one/multiple
  ``..`` escapes, root-prefix-confusion paths, empty keys, and symlink escapes
  are rejected via resolved-path containment — never naive string checks;
* writes stream in bounded chunks from the current source position to a
  temporary file and atomically replace into the final path; duplicate and
  failed writes leave the final object untouched and clean the temp file
  best-effort;
* binary and zero-byte content round-trip exactly; ``open`` returns a fresh
  streaming reader; ``exists`` answers only for regular files (directories are
  not content objects).
"""

import os
from io import BytesIO

import pytest

from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
from ava.repositories import StoredContentInfo
from ava.repositories.attachment_content_store import AttachmentContentStore


def _store(root):
    return LocalAttachmentContentStore(root)


# ============================================================
# BEGIN: Root initialization
# ============================================================


def test_missing_root_directory_is_created_with_parents(tmp_path) -> None:
    """A configured root that does not exist is created, parents included."""
    root = tmp_path / "deep" / "nested" / "storage"
    store = _store(root)

    assert root.is_dir()
    store.put("attachments/doc-1/source.bin", BytesIO(b"data"))
    assert (root / "attachments" / "doc-1" / "source.bin").is_file()


def test_root_that_is_a_file_fails_construction(tmp_path) -> None:
    """A configured root that exists but is not a directory fails clearly."""
    root = tmp_path / "a-file"
    root.write_bytes(b"not a directory")

    with pytest.raises(ValueError, match="not a directory"):
        _store(root)


# ============================================================
# END: Root initialization
# ============================================================


# ============================================================
# BEGIN: Storage-key containment
# ============================================================


def test_absolute_storage_keys_are_rejected(tmp_path) -> None:
    """Absolute paths are never normalized into the storage root."""
    store = _store(tmp_path / "root")

    with pytest.raises(ValueError, match="relative logical key"):
        store.put(str(tmp_path / "absolute.bin"), BytesIO(b"x"))
    with pytest.raises(ValueError):
        store.exists(str(tmp_path / "absolute.bin"))
    with pytest.raises(ValueError):
        store.open(str(tmp_path / "absolute.bin"))


@pytest.mark.parametrize(
    "key",
    [
        "../outside.txt",
        "attachments/../../outside.txt",
        "attachments/a/../../../outside.txt",
    ],
)
def test_parent_traversal_keys_are_rejected(tmp_path, key: str) -> None:
    """One and multiple ``..`` escapes must never escape the root."""
    store = _store(tmp_path / "root")
    (tmp_path / "outside.txt").write_bytes(b"host data")

    with pytest.raises(ValueError, match="parent traversal"):
        store.put(key, BytesIO(b"x"))
    with pytest.raises(ValueError):
        store.exists(key)
    with pytest.raises(ValueError):
        store.open(key)


def test_empty_storage_key_is_rejected(tmp_path) -> None:
    """An empty key resolves to the root itself and is refused."""
    store = _store(tmp_path / "root")

    with pytest.raises(ValueError, match="must not be empty"):
        store.put("", BytesIO(b"x"))
    with pytest.raises(ValueError):
        store.exists("")
    with pytest.raises(ValueError):
        store.open("")


def test_sibling_prefix_path_cannot_escape_the_root(tmp_path) -> None:
    """Containment uses resolved ancestry, never naive string prefixing.

    Root ``ava`` and sibling ``ava-evil`` share a string prefix: under a naive
    prefix check a ``../`` step back toward the sibling would be unsafe, and a
    sibling-prefixed key must still be legal *inside* the root.
    """
    root = tmp_path / "ava"
    sibling = tmp_path / "ava-evil"
    sibling.mkdir()
    (sibling / "file").write_bytes(b"nope")
    store = _store(root)

    with pytest.raises(ValueError):
        store.exists("../ava-evil/file")

    store.put("ava-evil/file", BytesIO(b"ok"))
    assert store.exists("ava-evil/file")
    assert (root / "ava-evil" / "file").is_file()


@pytest.mark.skipif(os.name == "nt", reason="symlink privileges unavailable on Windows")
def test_symlink_escaping_the_root_is_rejected(tmp_path) -> None:
    """A storage key resolving through a symlink outside the root is refused."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    store = _store(root)

    with pytest.raises(ValueError):
        store.exists("link/secret.bin")
    with pytest.raises(ValueError):
        store.open("link/secret.bin")
    with pytest.raises(ValueError):
        store.put("link/secret.bin", BytesIO(b"x"))


# ============================================================
# END: Storage-key containment
# ============================================================


# ============================================================
# BEGIN: Round trips
# ============================================================


def test_valid_nested_key_writes_successfully(tmp_path) -> None:
    """``attachments/a/file.bin`` works and lands beneath the root."""
    store = _store(tmp_path / "root")

    result = store.put("attachments/a/file.bin", BytesIO(b"content"))

    assert result.size_bytes == len(b"content")
    assert (tmp_path / "root" / "attachments" / "a" / "file.bin").read_bytes() == b"content"
    assert store.open("attachments/a/file.bin").read() == b"content"


def test_binary_content_round_trips_byte_exactly(tmp_path) -> None:
    """Arbitrary binary data (null bytes, 0xFF, non-UTF8) survives intact."""
    store = _store(tmp_path / "root")
    payload = b"\x00\x01\xff\x00binary\xff\xfe\x00\x0b\x0c\x1f\x80\x00tail\x00"

    result = store.put("attachments/doc-2/blob.bin", BytesIO(payload))

    assert result.size_bytes == len(payload)
    assert store.open("attachments/doc-2/blob.bin").read() == payload


def test_zero_byte_content_stores_reads_back_empty(tmp_path) -> None:
    """``put`` of an empty stream yields a real empty file with size 0."""
    store = _store(tmp_path / "root")

    result = store.put("empty.bin", BytesIO(b""))

    assert isinstance(result, StoredContentInfo)
    assert result.size_bytes == 0
    assert store.exists("empty.bin")
    assert store.open("empty.bin").read() == b""
    assert (tmp_path / "root" / "empty.bin").is_file()


def test_put_reports_authoritative_stored_byte_count(tmp_path) -> None:
    """The reported size equals the bytes actually written, not caller metadata."""
    store = _store(tmp_path / "root")
    payload = b"x" * 70000  # force multiple bounded reads

    result = store.put("k", BytesIO(payload))

    assert result.size_bytes == 70000
    assert len(store.open("k").read()) == 70000


def test_put_reads_incrementally_with_bounded_chunks(tmp_path) -> None:
    """The store streams; it never asks for a whole-file read."""
    store = _store(tmp_path / "root")
    source = _RecordingReadStream(b"z" * 70_000)

    result = store.put("k", source)

    assert result.size_bytes == 70_000
    assert len(store.open("k").read()) == 70_000
    assert source.requested_sizes, "store must read through the streaming API"
    assert all(size > 0 for size in source.requested_sizes)
    assert source.requested_sizes[0] < 70_000, "first read must not request the whole file"
    assert 70_000 not in source.requested_sizes, "whole-file read requested"


# ============================================================
# END: Round trips
# ============================================================


# ============================================================
# BEGIN: Stream ownership and position semantics
# ============================================================


def test_put_does_not_close_the_caller_source(tmp_path) -> None:
    """The caller keeps ownership of the input stream after ``put``."""
    store = _store(tmp_path / "root")
    source = BytesIO(b"still mine")

    store.put("k", source)

    assert source.closed is False
    assert source.read() == b""


def test_put_reads_from_current_stream_position(tmp_path) -> None:
    """No hidden rewind: reading starts at the current cursor."""
    store = _store(tmp_path / "root")
    source = BytesIO(b"abcdef")
    source.read(2)

    result = store.put("k", source)

    assert result.size_bytes == 4
    assert store.open("k").read() == b"cdef"


def test_put_supports_a_non_seekable_source(tmp_path) -> None:
    """``put`` works on a stream that only supports ``read(size)``."""
    store = _store(tmp_path / "root")
    source = _NonSeekableStream(b"streamed without seeking")

    result = store.put("k", source)

    assert result.size_bytes == len(b"streamed without seeking")
    assert store.open("k").read() == b"streamed without seeking"


class _NonSeekableStream:
    """Minimal file-like double supporting only ``read(size)`` (no seek/tell)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int) -> bytes:
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


class _RecordingReadStream:
    """File-like double that records requested read sizes and forbids no-arg reads."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise AssertionError("read() must be called with an explicit size")
        self.requested_sizes.append(size)
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


# ============================================================
# END: Stream ownership and position semantics
# ============================================================


# ============================================================
# BEGIN: Duplicate keys and failed writes
# ============================================================


def test_duplicate_key_is_rejected_and_original_preserved(tmp_path) -> None:
    """A duplicate ``put`` raises ``ValueError`` and never clobbers the bytes."""
    store = _store(tmp_path / "root")
    store.put("k", BytesIO(b"original"))

    with pytest.raises(ValueError, match="already exists"):
        store.put("k", BytesIO(b"replacement"))

    assert store.open("k").read() == b"original"
    assert store.exists("k") is True
    leftovers = list((tmp_path / "root").iterdir())
    assert leftovers == [tmp_path / "root" / "k"], "only the final object may remain"


def test_failed_write_leaves_no_final_object_and_cleans_temp(tmp_path) -> None:
    """A source that fails mid-write leaves nothing at the final path."""
    store = _store(tmp_path / "root")

    with pytest.raises(OSError, match="source failed"):
        store.put("k", _FailingSource())

    assert store.exists("k") is False
    assert not list((tmp_path / "root").iterdir()), "temp file must be cleaned best-effort"


def test_delete_prunes_empty_directories_left_by_a_failed_write(tmp_path) -> None:
    root = tmp_path / "root"
    store = _store(root)
    key = "attachments/attachment-1/content"

    with pytest.raises(OSError, match="source failed"):
        store.put(key, _FailingSource())

    assert (root / "attachments" / "attachment-1").is_dir()
    assert store.delete(key) is False
    assert not (root / "attachments").exists()


class _FailingSource:
    """Source stream that raises on the first bounded read."""

    def read(self, size: int) -> bytes:
        raise OSError("source failed")


# ============================================================
# END: Duplicate keys and failed writes
# ============================================================


# ============================================================
# BEGIN: open and exists behavior
# ============================================================


def test_open_returns_a_fresh_streaming_reader_per_call(tmp_path) -> None:
    """Each call yields an independent stream; closing one affects nothing."""
    store = _store(tmp_path / "root")
    store.put("k", BytesIO(b"payload"))

    first = store.open("k")
    first.close()

    second = store.open("k")
    assert second.read() == b"payload"
    second.close()

    third = store.open("k")
    assert third.read() == b"payload"
    third.close()
    assert store.open("k").read() == b"payload"


def test_open_unknown_key_raises_file_not_found(tmp_path) -> None:
    """``open`` on a missing key raises ``FileNotFoundError``, never ``None``."""
    store = _store(tmp_path / "root")

    with pytest.raises(FileNotFoundError):
        store.open("no-such-key")


def test_exists_reports_known_and_missing_state(tmp_path) -> None:
    """Known regular files exist; missing keys do not; checking is side-effect-free."""
    store = _store(tmp_path / "root")
    store.put("known", BytesIO(b"data"))

    assert store.exists("known") is True
    assert store.exists("unknown") is False
    assert store.exists("known") is True
    assert store.exists("unknown") is False


def test_directory_keys_are_not_content_objects(tmp_path) -> None:
    """A key resolving to a directory is not valid stored content."""
    store = _store(tmp_path / "root")
    store.put("attachments/a/file.bin", BytesIO(b"data"))

    assert store.exists("attachments") is False
    assert store.exists("attachments/a") is False
    with pytest.raises(FileNotFoundError):
        store.open("attachments/a")


def test_put_rejects_a_key_colliding_with_an_existing_directory(tmp_path) -> None:
    """A write colliding with a directory (an invalid content path) is refused."""
    store = _store(tmp_path / "root")
    store.put("attachments/a/file.bin", BytesIO(b"x"))

    with pytest.raises(ValueError, match="already exists"):
        store.put("attachments/a", BytesIO(b"y"))


def test_stored_content_lands_only_under_the_configured_root(tmp_path) -> None:
    """The physical files stay beneath the root; no stray paths outside."""
    root = tmp_path / "root"
    store = _store(root)
    store.put("attachments/doc-1/source.bin", BytesIO(b"payload"))

    assert (root / "attachments" / "doc-1" / "source.bin").read_bytes() == b"payload"
    assert not list((tmp_path / "doc-1").glob("*"))


def test_delete_prunes_empty_attachment_directories_but_keeps_the_storage_root(tmp_path) -> None:
    root = tmp_path / "root"
    store = _store(root)
    key = "attachments/attachment-1/content"
    store.put(key, BytesIO(b"payload"))

    assert store.delete(key) is True

    assert root.is_dir()
    assert not (root / "attachments").exists()
    assert store.delete(key) is False


def test_delete_keeps_shared_directory_until_its_last_attachment_is_removed(tmp_path) -> None:
    root = tmp_path / "root"
    store = _store(root)
    first = "attachments/attachment-1/content"
    second = "attachments/attachment-2/content"
    store.put(first, BytesIO(b"first"))
    store.put(second, BytesIO(b"second"))

    assert store.delete(first) is True
    assert (root / "attachments").is_dir()
    assert not (root / "attachments" / "attachment-1").exists()
    assert store.exists(second)

    assert store.delete(second) is True
    assert not (root / "attachments").exists()


def test_content_survives_store_reconstruction_on_the_same_root(tmp_path) -> None:
    """A brand-new store instance over the same root returns the original bytes.

    Step 4.14.H local-content restart-durability closure: the physical content
    is durable independently of process memory. Write through one instance,
    discard it, build a fresh ``LocalAttachmentContentStore`` over the same
    configured root, and the original binary and zero-byte objects must be
    readable exactly as stored.
    """
    root = tmp_path / "storage"
    payload = b"\x00\x01\xffbinary\xfe\x00tail\x00"
    first = LocalAttachmentContentStore(root)
    try:
        first.put("attachments/doc-1/blob.bin", BytesIO(payload))
        first.put("legacy/empty.bin", BytesIO(b""))
    finally:
        first = None  # discard the first instance completely

    second = LocalAttachmentContentStore(root)
    assert second.exists("attachments/doc-1/blob.bin")
    assert second.open("attachments/doc-1/blob.bin").read() == payload
    assert (root / "attachments" / "doc-1" / "blob.bin").read_bytes() == payload
    assert second.exists("legacy/empty.bin")
    assert second.open("legacy/empty.bin").read() == b""


# ============================================================
# END: open and exists behavior
# ============================================================


# ============================================================
# BEGIN: Port conformance
# ============================================================


def test_local_store_conforms_to_the_content_store_port(tmp_path) -> None:
    """The local adapter satisfies the ``AttachmentContentStore`` contract."""
    store = _store(tmp_path / "root")
    assert isinstance(store, AttachmentContentStore)
    assert AttachmentContentStore.__abstractmethods__ == frozenset({"put", "open", "exists"})


# ============================================================
# END: Port conformance
# ============================================================
