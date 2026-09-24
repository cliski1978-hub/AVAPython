"""Attachment restart/recovery closure tests (Step 4.14.H).

Prove the attachment foundation is genuinely durable across an application
restart when composed with its two production-friendly adapters (relational
metadata + local content), end to end through the real API chain — no service
doubles, no mocked stores:

* a multipart upload through the real route → ``AttachmentService`` →
  ``RelationalAttachmentRepository`` → ``LocalAttachmentContentStore`` chain
  returns 201 ``available`` with server-owned identity and the stored size;
* the metadata id is then readable, owner-listed, and the content streams back
  byte-exact;
* after the application + persistence are disposed and discarded, a fresh
  application over the *same* SQLite database and *same* storage root restores
  the metadata (``available``, size exact, owner pair exact) and streams the
  same exact bytes — physical content durability independent of process memory;
* zero-byte content is a real empty object across restart (never treated as
  missing content);
* hostile display filenames stay display-only under local storage: the storage
  key is derived from the attachment id, physical placement stays under the
  configured root, and download headers remain safe.

These are attachment-specific recovery evidence only. The wider application
restart/recovery story (conversations/messages/runs/documents/revisions) is
Step 4.15 and is deliberately not started here.
"""

from typing import Any

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.version import CONTRACT_VERSION

BINARY_PAYLOAD = bytes(range(256)) * 100  # multi-chunk, non-UTF8-safe binary


def _settings(tmp_path, suffix: str = "") -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / f"ava{suffix}.sqlite3"),
        attachment_storage="local",
        attachment_storage_root=str(tmp_path / "content"),
    )


def _upload(client: TestClient, *, content: bytes, file_name: str, media_type: str, **owner: str) -> dict[str, Any]:
    response = client.post(
        "/attachments",
        files={"file": (file_name, content, media_type)},
        data=owner or None,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_api_end_to_end_restart_smoke_relational_metadata_local_content(tmp_path) -> None:
    """The real relational+local chain uploads, reads, lists, streams, then recovers after restart."""
    settings = _settings(tmp_path)

    first_app = create_app(settings=settings)
    first = TestClient(first_app)
    with first:
        created = _upload(
            first,
            content=BINARY_PAYLOAD,
            file_name="report.bin",
            media_type="application/octet-stream",
            owner_type="document",
            owner_id="doc-9",
        )

    # Step 4.14.H closure chain: the whole API path over the real adapters.
    assert created["status"] == "available"
    assert created["size_bytes"] == len(BINARY_PAYLOAD)
    assert created["owner_type"] == "document"
    assert created["owner_id"] == "doc-9"
    assert created["contract_version"] == CONTRACT_VERSION
    assert created["attachment_id"]
    assert created["created_at"]

    with first:
        metadata = first.get(f"/attachments/{created['attachment_id']}")
        assert metadata.status_code == 200
        assert metadata.json() == created

        listed = first.get("/attachments", params={"owner_type": "document", "owner_id": "doc-9"})
        assert listed.status_code == 200
        assert [item["attachment_id"] for item in listed.json()["attachments"]] == [created["attachment_id"]]

        download = first.get(f"/attachments/{created['attachment_id']}/content")
        assert download.status_code == 200
        assert download.content == BINARY_PAYLOAD

    # --- restart: dispose/discard the application and persistence entirely ---
    first_app.state.persistence.dispose()
    first_app = None

    second_app = create_app(settings=settings)
    second = TestClient(second_app)
    with second:
        restored = second.get(f"/attachments/{created['attachment_id']}")
        assert restored.status_code == 200
        restored_body = restored.json()
        assert restored_body["status"] == "available"
        assert restored_body["size_bytes"] == len(BINARY_PAYLOAD)
        assert restored_body["owner_type"] == "document"
        assert restored_body["owner_id"] == "doc-9"
        assert restored_body["file_name"] == "report.bin"

        restored_list = second.get("/attachments", params={"owner_type": "document", "owner_id": "doc-9"})
        assert [item["attachment_id"] for item in restored_list.json()["attachments"]] == [
            created["attachment_id"]
        ]

        restored_download = second.get(f"/attachments/{created['attachment_id']}/content")
        assert restored_download.status_code == 200
        assert restored_download.content == BINARY_PAYLOAD

    # Physical proof: the file lives under the configured content root at the
    # id-derived storage key — not under any filename-derived path.
    physical = tmp_path / "content" / "attachments" / created["attachment_id"] / "content"
    assert physical.is_file()
    assert physical.read_bytes() == BINARY_PAYLOAD


def test_zero_byte_attachment_survives_restart(tmp_path) -> None:
    """A zero-byte attachment is a real empty object that persists across restart."""
    settings = _settings(tmp_path, suffix="-zero")

    first_app = create_app(settings=settings)
    with TestClient(first_app) as first:
        created = _upload(first, content=b"", file_name="empty.bin", media_type="application/octet-stream")

    assert created["status"] == "available"
    assert created["size_bytes"] == 0

    with first:
        download = first.get(f"/attachments/{created['attachment_id']}/content")
        assert download.status_code == 200
        assert download.content == b""

    first_app.state.persistence.dispose()

    second_app = create_app(settings=settings)
    with TestClient(second_app) as second:
        restored = second.get(f"/attachments/{created['attachment_id']}")
        assert restored.status_code == 200
        assert restored.json()["status"] == "available"
        assert restored.json()["size_bytes"] == 0

        download = second.get(f"/attachments/{created['attachment_id']}/content")
        assert download.status_code == 200
        assert download.content == b""

    physical = tmp_path / "content" / "attachments" / created["attachment_id"] / "content"
    assert physical.is_file()
    assert physical.read_bytes() == b""


def test_hostile_filename_stays_display_only_under_local_storage(tmp_path) -> None:
    """A path/quote-laden display name never becomes a storage key or escapes the root."""
    settings = _settings(tmp_path, suffix="-hostile")
    hostile = '../../dangerous"name'

    app = create_app(settings=settings)
    with TestClient(app) as client:
        created = _upload(
            client,
            content=b"x",
            file_name=hostile,
            media_type="text/plain",
            owner_type="document",
            owner_id="doc-1",
        )
        download = client.get(f"/attachments/{created['attachment_id']}/content")

    # Wire response preserves the path-like display name (the quote arrives
    # transport-encoded as %22) and the header stays a safe single line.
    assert created["file_name"].startswith("../..")  # never narrowed to a safe basename
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "inline" not in disposition

    # Storage key is derived from the attachment id; the filename never
    # participates in any physical placement and nothing escapes the root.
    key = f"attachments/{created['attachment_id']}/content"
    physical = tmp_path / "content" / "attachments" / created["attachment_id"] / "content"
    assert physical.is_file()
    assert physical.read_bytes() == b"x"

    assert not list((tmp_path / "content").glob("..*"))
    content_files = sorted(
        str(p.relative_to(tmp_path / "content"))
        for p in (tmp_path / "content").rglob("*")
        if p.is_file()
    )
    assert content_files == [key]