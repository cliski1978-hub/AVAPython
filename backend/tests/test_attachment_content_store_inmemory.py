"""InMemoryAttachmentContentStore behavior tests (Step 4.14.B).

Prove the streaming contract on the development/test adapter:

* ``put`` reads from the source's current position until EOF, in bounded
  chunks, never closes the caller's stream, and never requires seek/tell;
* stored bytes round-trip byte-exactly (including arbitrary binary data);
* duplicate keys are rejected without disturbing existing content;
* ``open`` returns a fresh caller-owned stream and raises ``FileNotFoundError``
  for unknown keys;
* zero-byte content is valid and ``clear`` restores the initial state.

The content store knows nothing about attachment metadata (Step 4.14.A) —
only ``storage_key``, binary content, and stored-content info.
"""

from io import BytesIO

import pytest

from ava.repositories import StoredContentInfo
from ava.repositories.attachment_content_store import AttachmentContentStore
from ava.services.attachment_content_store import InMemoryAttachmentContentStore


def _make_store() -> InMemoryAttachmentContentStore:
    """Create a fresh store for each test."""
    return InMemoryAttachmentContentStore()


def test_store_conforms_to_the_content_store_port() -> None:
    """The in-memory adapter satisfies the ``AttachmentContentStore`` contract."""
    store = _make_store()
    assert isinstance(store, AttachmentContentStore)
    assert AttachmentContentStore.__abstractmethods__ == frozenset({"put", "open", "exists"})


# ============================================================
# BEGIN: Round trips
# ============================================================


def test_put_open_exact_round_trip() -> None:
    """Bytes put in are the exact bytes read back."""
    store = _make_store()
    source = BytesIO(b"the quick brown fox jumps over the lazy dog")

    result = store.put("attachments/doc-1/source.txt", source)

    assert result.size_bytes == len(b"the quick brown fox jumps over the lazy dog")
    assert store.open("attachments/doc-1/source.txt").read() == (
        b"the quick brown fox jumps over the lazy dog"
    )


def test_put_reports_authoritative_stored_byte_count() -> None:
    """The reported size equals the bytes actually stored, not caller-supplied."""
    store = _make_store()
    payload = b"x" * 70000  # force multiple bounded reads

    result = store.put("k", BytesIO(payload))

    assert isinstance(result, StoredContentInfo)
    assert result.size_bytes == 70000
    assert len(store.open("k").read()) == 70000


def test_binary_content_round_trips_byte_exactly() -> None:
    """Arbitrary binary data (null bytes, 0xFF, non-UTF8) survives intact."""
    store = _make_store()
    payload = b"\x00\x01\xff\x00binary\xff\xfe\x00\x0b\x0c\x1f\x80\x00tail\x00"

    result = store.put("attachments/doc-2/blob.bin", BytesIO(payload))

    assert result.size_bytes == len(payload)
    assert store.open("attachments/doc-2/blob.bin").read() == payload


# ============================================================
# END: Round trips
# ============================================================


# ============================================================
# BEGIN: exists
# ============================================================


def test_exists_reports_storage_state_without_side_effects() -> None:
    """Known keys exist; unknown keys do not; checking changes nothing."""
    store = _make_store()
    store.put("known", BytesIO(b"data"))

    assert store.exists("known") is True
    assert store.exists("unknown") is False
    assert store.exists("known") is True
    assert store.exists("unknown") is False


# ============================================================
# END: exists
# ============================================================


# ============================================================
# BEGIN: Zero-byte content
# ============================================================


def test_empty_content_is_valid() -> None:
    """Zero-byte content stores, exists, and reads back as ``b\"\"``."""
    store = _make_store()

    result = store.put("empty", BytesIO(b""))

    assert result.size_bytes == 0
    assert store.exists("empty") is True
    assert store.open("empty").read() == b""


# ============================================================
# END: Zero-byte content
# ============================================================


# ============================================================
# BEGIN: Duplicate keys
# ============================================================


def test_duplicate_storage_key_is_rejected() -> None:
    """Putting the same opaque key twice raises ``ValueError``."""
    store = _make_store()
    store.put("attachments/doc-1/source", BytesIO(b"first"))

    with pytest.raises(ValueError):
        store.put("attachments/doc-1/source", BytesIO(b"second"))


def test_failed_duplicate_leaves_existing_content_unchanged() -> None:
    """A rejected overwrite must not clobber the original bytes."""
    store = _make_store()
    store.put("k", BytesIO(b"original"))

    with pytest.raises(ValueError):
        store.put("k", BytesIO(b"replacement"))

    assert store.open("k").read() == b"original"
    assert store.exists("k") is True


# ============================================================
# END: Duplicate keys
# ============================================================


# ============================================================
# BEGIN: open behavior
# ============================================================


def test_open_unknown_key_raises_file_not_found() -> None:
    """``open`` on a missing key raises ``FileNotFoundError``, never ``None``."""
    store = _make_store()

    with pytest.raises(FileNotFoundError):
        store.open("no-such-key")


def test_open_returns_a_fresh_stream_per_call() -> None:
    """Each call yields an independent stream; closing one affects nothing."""
    store = _make_store()
    store.put("k", BytesIO(b"payload"))

    first = store.open("k")
    first.close()

    second = store.open("k")
    assert second.read() == b"payload"

    third = store.open("k")
    assert third.read() == b"payload"
    third.close()
    assert store.open("k").read() == b"payload"


# ============================================================
# END: open behavior
# ============================================================


# ============================================================
# BEGIN: Stream ownership and position semantics
# ============================================================


def test_put_does_not_close_the_caller_source() -> None:
    """The caller keeps ownership of the input stream after ``put``."""
    store = _make_store()
    source = BytesIO(b"still mine")

    store.put("k", source)

    assert source.closed is False
    assert source.read() == b""


def test_put_reads_from_current_stream_position() -> None:
    """No hidden rewind: reading starts at the current cursor."""
    store = _make_store()
    source = BytesIO(b"abcdef")
    source.read(2)

    result = store.put("k", source)

    assert result.size_bytes == 4
    assert store.open("k").read() == b"cdef"


def test_put_supports_a_non_seekable_source() -> None:
    """``put`` works on a stream that only supports ``read(size)``."""
    store = _make_store()
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


def test_put_reads_incrementally_with_bounded_chunks() -> None:
    """The store never asks for a whole-file read and reads in positive sizes."""
    store = _make_store()
    source = _RecordingReadStream(b"z" * 70_000)

    result = store.put("k", source)

    assert result.size_bytes == 70_000
    assert len(store.open("k").read()) == 70_000
    assert source.requested_sizes, "store must read through the streaming API"
    assert all(size > 0 for size in source.requested_sizes)
    assert source.requested_sizes[0] < 70_000, "first read must not request the whole file"
    assert 70_000 not in source.requested_sizes, "whole-file read requested"


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
# BEGIN: clear helper
# ============================================================


def test_clear_resets_the_store_to_its_initial_state() -> None:
    """After ``clear``, keys are gone and previously used keys are reusable."""
    store = _make_store()
    store.put("k1", BytesIO(b"one"))
    store.put("k2", BytesIO(b"two"))
    store.put("k3", BytesIO(b""))

    store.clear()

    assert store.exists("k1") is False
    assert store.exists("k2") is False
    assert store.exists("k3") is False
    with pytest.raises(FileNotFoundError):
        store.open("k1")

    result = store.put("k1", BytesIO(b"reused"))
    assert result.size_bytes == len(b"reused")
    assert store.open("k1").read() == b"reused"


# ============================================================
# END: clear helper
# ============================================================