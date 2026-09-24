"""Attachment API tests (Step 4.14.F).

API-level coverage for the attachment transport layer: multipart upload,
metadata read, owner-scoped listing, and content download through
``/attachments``. These tests pin the routing semantics (201/200/404/409/422/
500), the mapping seam (responses reflect exactly the stored metadata), header
safety (no CR/LF injection, keywords-only download), and the absence of
storage internals on the wire.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.api.routes.attachments import _content_disposition, _missing_file_name
from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.contracts.version import CONTRACT_VERSION
from ava.repositories.attachment_repository import AttachmentRecord
from ava.services.attachment_service import AttachmentStorageError

ATTACHMENT_RESPONSE_FIELDS = {
    "attachment_id",
    "file_name",
    "media_type",
    "size_bytes",
    "owner_type",
    "owner_id",
    "status",
    "created_at",
    "contract_version",
}

# ============================================================
# BEGIN: Helpers
# ============================================================


def make_app() -> FastAPI:
    """Return a default application with the shared attachment service."""
    return create_app()


def upload(
    client: TestClient,
    *,
    content: bytes = b"hello",
    file_name: str = "report.txt",
    media_type: str = "text/plain",
    owner_type: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Upload a multipart attachment and return the parsed 201 body."""
    data: dict[str, str] = {}
    if owner_type is not None:
        data["owner_type"] = owner_type
    if owner_id is not None:
        data["owner_id"] = owner_id
    response = client.post(
        "/attachments",
        files={"file": (file_name, content, media_type)},
        data=data,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


class RecordingService:
    """Duck-typed attachment service that records create_attachment calls."""

    def __init__(self) -> None:
        self.create_calls: list[tuple[str, str]] = []

    def create_attachment(self, *, file_name: str, media_type: str, **_: Any) -> Any:
        self.create_calls.append((file_name, media_type))
        raise AssertionError("recording service must not reach storage")


class FailingUploadService:
    """Attachment service double that fails every upload."""

    def create_attachment(self, **_: Any) -> Any:
        raise AttachmentStorageError("boom")


class FailingContentService:
    """Attachment service double that fails every content open."""

    def open_attachment_content(self, attachment_id: str) -> Any:
        raise AttachmentStorageError("boom")


def insert_record(app: FastAPI, record: AttachmentRecord) -> None:
    """Insert a raw metadata record behind the service's back."""
    app.state.persistence.attachment_repository.create(record)


def make_record(
    *,
    attachment_id: str,
    status: AttachmentStatus,
    owner_type: AttachmentOwnerType | None = None,
    owner_id: str | None = None,
) -> AttachmentRecord:
    """Build a frozen metadata record for direct repository insertion."""
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name="raw.bin",
        media_type="application/octet-stream",
        size_bytes=0,
        storage_key=f"attachments/{attachment_id}/content",
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Create Attachment
# ============================================================


def test_upload_returns_201_with_exact_wire_shape() -> None:
    """A valid upload returns 201 with exactly the approved response fields."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, file_name="report.pdf", content=b"<pdf>", media_type="application/pdf")

    assert set(body) == ATTACHMENT_RESPONSE_FIELDS
    assert body["file_name"] == "report.pdf"
    assert body["media_type"] == "application/pdf"
    assert body["size_bytes"] == 5
    assert body["status"] == AttachmentStatus.AVAILABLE.value
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["attachment_id"]
    assert body["created_at"].endswith(("Z", "+00:00"))


def test_upload_generates_server_owned_identifier() -> None:
    """Clients never supply the id; the service mints a distinct one per upload."""
    app = make_app()
    with TestClient(app) as client:
        first = upload(client, file_name="a.txt")
        second = upload(client, file_name="b.txt")

    assert first["attachment_id"] != second["attachment_id"]


def test_upload_with_owner_pair_associates_the_attachment() -> None:
    """A both-set owner pair lands on the wire unchanged."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(
            client,
            owner_type="document",
            owner_id="doc-7",
        )

    assert body["owner_type"] == "document"
    assert body["owner_id"] == "doc-7"


def test_upload_without_owner_fields_is_unassociated() -> None:
    """An omitted owner pair is unassociated (both fields null)."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client)

    assert body["owner_type"] is None
    assert body["owner_id"] is None


def test_upload_with_half_owner_pair_is_rejected_before_storage() -> None:
    """A half-set owner pair is 422 and never reaches the service/store."""
    app = make_app()
    probe = RecordingService()
    app.state.attachment_service = probe
    with TestClient(app) as client:
        type_only = client.post(
            "/attachments",
            files={"file": ("a.txt", b"x", "text/plain")},
            data={"owner_type": "document"},
        )
        id_only = client.post(
            "/attachments",
            files={"file": ("b.txt", b"x", "text/plain")},
            data={"owner_id": "doc-1"},
        )

    assert type_only.status_code == 422
    assert id_only.status_code == 422
    assert type_only.json()["error_code"] == "invalid_owner_pair"
    assert id_only.json()["error_code"] == "invalid_owner_pair"
    assert probe.create_calls == []


def test_upload_without_filename_is_rejected() -> None:
    """An upload with an absent filename is rejected (422) before any storage."""
    app = make_app()
    probe = RecordingService()
    app.state.attachment_service = probe
    with TestClient(app) as client:
        empty_name = client.post("/attachments", files={"file": ("", b"x", "text/plain")})
        no_name = client.post("/attachments", files={"file": (None, b"x", "text/plain")})

    assert empty_name.status_code == 422
    assert no_name.status_code == 422
    assert probe.create_calls == []


def test_zero_byte_upload_is_valid() -> None:
    """A zero-byte attachment uploads cleanly with size 0."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, content=b"", file_name="empty.bin")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    assert body["size_bytes"] == 0
    assert download.status_code == 200
    assert download.content == b""


def test_binary_content_round_trips_exactly() -> None:
    """Multi-chunk binary bytes stream back byte-for-byte."""
    payload = bytes(range(256)) * 400
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, content=payload, file_name="blob.bin", media_type="application/octet-stream")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    assert body["size_bytes"] == len(payload)
    assert download.content == payload


def test_upload_response_never_exposes_storage_internals() -> None:
    """The upload response leak-checks: no storage key, path, or store details."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client)
        text = client.get(f"/attachments/{body['attachment_id']}/content").text

    attached_bytes = f"attachments/{body['attachment_id']}/content"
    assert "storage_key" not in body
    assert "content_store" not in body
    assert "storage" not in set(body)
    assert attached_bytes not in str(body)
    assert attached_bytes not in text


def test_upload_storage_failure_maps_to_500_without_internals() -> None:
    """A storage fault is a stable 500 that never leaks the underlying error."""
    app = make_app()
    app.state.attachment_service = FailingUploadService()
    with TestClient(app) as client:
        response = client.post(
            "/attachments",
            files={"file": ("a.txt", b"x", "text/plain")},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "attachment_storage_failure"
    assert body["category"] == "internal"
    assert "boom" not in response.text
    assert "storage_key" not in body
    assert "content" not in body


# ============================================================
# END: Create Attachment
# ============================================================


# ============================================================
# BEGIN: Get Attachment Metadata
# ============================================================


def test_metadata_for_known_attachment_matches_the_record() -> None:
    """GET metadata returns the stored snapshot mapped field-for-field."""
    app = make_app()
    with TestClient(app) as client:
        created = upload(client, file_name="map.txt", content=b"abc")
        response = client.get(f"/attachments/{created['attachment_id']}")
        record = app.state.persistence.attachment_repository.get(created["attachment_id"])

    assert response.status_code == 200
    body = response.json()
    assert record is not None
    assert body["attachment_id"] == record.attachment_id
    assert body["file_name"] == record.file_name
    assert body["media_type"] == record.media_type
    assert body["size_bytes"] == record.size_bytes
    assert body["owner_type"] == record.owner_type
    assert body["owner_id"] == record.owner_id
    assert body["status"] == record.status.value
    assert body["created_at"].endswith(("Z", "+00:00"))


def test_metadata_for_unknown_attachment_is_404() -> None:
    """An unknown id returns 404, never a bare content store probe."""
    app = make_app()
    with TestClient(app) as client:
        response = client.get("/attachments/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error_code"] == "attachment_not_found"


def test_pending_and_failed_metadata_are_described() -> None:
    """Metadata describes lifecycle state and never touches the content store."""
    app = make_app()
    insert_record(app, make_record(attachment_id="pending-1", status=AttachmentStatus.PENDING))
    insert_record(app, make_record(attachment_id="failed-1", status=AttachmentStatus.FAILED))
    with TestClient(app) as client:
        pending = client.get("/attachments/pending-1")
        failed = client.get("/attachments/failed-1")

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"


# ============================================================
# END: Get Attachment Metadata
# ============================================================


# ============================================================
# BEGIN: List Attachments
# ============================================================


def test_owner_list_isolation_and_stable_order() -> None:
    """Listing is owner-scoped and preserves insertion order within an owner."""
    app = make_app()
    with TestClient(app) as client:
        doc_one = [upload(client, file_name=f"{i}.txt", owner_type="document", owner_id="doc-1") for i in range(3)]
        doc_two = [upload(client, file_name=f"{i}.txt", owner_type="document", owner_id="doc-2") for i in range(2)]

        first_list = client.get("/attachments", params={"owner_type": "document", "owner_id": "doc-1"})
        second_list = client.get("/attachments", params={"owner_type": "document", "owner_id": "doc-2"})

    assert first_list.status_code == 200
    first_body = first_list.json()
    assert first_body["owner_type"] == "document"
    assert first_body["owner_id"] == "doc-1"
    assert first_body["contract_version"] == CONTRACT_VERSION
    assert [item["attachment_id"] for item in first_body["attachments"]] == [
        item["attachment_id"] for item in doc_one
    ]
    assert [item["attachment_id"] for item in second_list.json()["attachments"]] == [
        item["attachment_id"] for item in doc_two
    ]


def test_list_requires_both_owner_parameters() -> None:
    """Missing owner query parameters is 422 — there is no global list."""
    app = make_app()
    with TestClient(app) as client:
        none_given = client.get("/attachments")
        type_only = client.get("/attachments", params={"owner_type": "document"})
        id_only = client.get("/attachments", params={"owner_id": "doc-1"})
        wrong_type = client.get("/attachments", params={"owner_type": "widget", "owner_id": "doc-1"})

    assert none_given.status_code == 422
    assert type_only.status_code == 422
    assert id_only.status_code == 422
    assert wrong_type.status_code == 422


# ============================================================
# END: List Attachments
# ============================================================


# ============================================================
# BEGIN: Get Attachment Content
# ============================================================


def test_content_download_headers_are_download_only() -> None:
    """Content streams with the upload media type and a safe attachment header."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, file_name="safe.txt", content=b"hello", media_type="text/plain")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    assert download.status_code == 200
    assert download.content == b"hello"
    assert download.headers["content-type"] == "text/plain"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "inline" not in disposition
    assert disposition == 'attachment; filename="safe.txt"'


def test_content_for_unknown_attachment_is_404() -> None:
    """Unknown content ids are 404 before the content store is consulted."""
    app = make_app()
    with TestClient(app) as client:
        response = client.get("/attachments/does-not-exist/content")

    assert response.status_code == 404
    assert response.json()["error_code"] == "attachment_not_found"


def test_content_for_pending_and_failed_is_409() -> None:
    """Pending/failed records never expose bytes: content is 409, not streamed."""
    app = make_app()
    insert_record(app, make_record(attachment_id="pending-9", status=AttachmentStatus.PENDING))
    insert_record(app, make_record(attachment_id="failed-9", status=AttachmentStatus.FAILED))
    with TestClient(app) as client:
        pending = client.get("/attachments/pending-9/content")
        failed = client.get("/attachments/failed-9/content")

    assert pending.status_code == 409
    assert pending.json()["error_code"] == "attachment_content_unavailable"
    assert pending.json()["category"] == "unavailable"
    assert failed.status_code == 409


def test_content_missing_despite_available_is_500() -> None:
    """An available record with missing bytes is an internal inconsistency: 500."""
    app = make_app()
    insert_record(
        app,
        make_record(
            attachment_id="phantom-1",
            status=AttachmentStatus.AVAILABLE,
        ),
    )
    with TestClient(app) as client:
        response = client.get("/attachments/phantom-1/content")

    assert response.status_code == 500
    assert response.json()["error_code"] == "attachment_storage_failure"


def test_content_open_storage_failure_is_500() -> None:
    """A storage fault while opening content is a stable 500 without internals."""
    app = make_app()
    app.state.attachment_service = FailingContentService()
    with TestClient(app) as client:
        response = client.get("/attachments/any-id/content")

    assert response.status_code == 500
    assert response.json()["error_code"] == "attachment_storage_failure"
    assert "boom" not in response.text


# ============================================================
# END: Get Attachment Content
# ============================================================


# ============================================================
# BEGIN: Hostile Filenames
# ============================================================


def test_path_like_filename_is_display_only() -> None:
    """A path-like display name is not interpreted and never becomes a key."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, file_name="../../report.pdf", content=b"x")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    assert body["file_name"] == "../../report.pdf"
    assert download.status_code == 200
    assert download.headers["content-disposition"] == 'attachment; filename="../../report.pdf"'


def test_quoted_filename_is_neutralized_in_the_header() -> None:
    """A display name with quotes cannot break the wire header: single-line, valid."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, file_name='quote"name.txt', content=b"x")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    disposition = download.headers["content-disposition"]
    assert download.status_code == 200
    assert disposition.startswith("attachment;")
    assert "\r" not in disposition
    assert "\n" not in disposition
    value = disposition[disposition.index("filename=") + len("filename=") :]
    assert value.startswith('"') and value.endswith('"')
    assert '"' not in value[1:-1]
    assert "%22" in value


def test_crlf_filename_cannot_tamper_headers() -> None:
    """Embedded CR/LF in a display name cannot inject response headers."""
    app = make_app()
    with TestClient(app) as client:
        response = client.post(
            "/attachments",
            files={"file": ("line\r\nInjected: evil", b"x", "text/plain")},
        )
        if response.status_code != 201:
            return
        body = response.json()
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    disposition = download.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert not disposition.lower().startswith("injected")


def test_unicode_filename_is_transported_safely() -> None:
    """Unicode names use the RFC 5987 filename* form; the header stays ASCII."""
    app = make_app()
    with TestClient(app) as client:
        body = upload(client, file_name="unicode-\u2713.txt", content=b"x")
        download = client.get(f"/attachments/{body['attachment_id']}/content")

    disposition = download.headers["content-disposition"]
    assert download.status_code == 200
    assert disposition.startswith('attachment; filename="unicode-.txt"')
    assert "filename*=UTF-8''" in disposition
    assert all(ord(ch) < 128 for ch in disposition)


# ============================================================
# END: Hostile Filenames
# ============================================================


# ============================================================
# BEGIN: Content-Disposition Sanitization (white-box)
# ============================================================


def test_content_disposition_strips_crlf_and_control_bytes() -> None:
    """Raw CR/LF/control bytes in a display name cannot tamper the header line."""
    header = _content_disposition("line\r\nInjected: evil")
    assert "\r" not in header
    assert "\n" not in header
    assert header.startswith("attachment;")

    control_header = _content_disposition("bad\x00\x1bpayload.txt")
    assert "\x00" not in control_header
    assert "\x1b" not in control_header


def test_content_disposition_neutralizes_quotes_and_backslashes() -> None:
    """Quote/backslash characters are neutralized inside the filename value."""
    assert _content_disposition('quote"name.txt') == 'attachment; filename="quote_name.txt"'
    assert "\\" not in _content_disposition("back\\slash.txt")


def test_content_disposition_encodes_unicode_with_filename_star() -> None:
    """Unicode names use RFC 5987 filename* and stay ASCII-only on the wire."""
    header = _content_disposition("unicode-\u2713.txt")
    assert all(ord(ch) < 128 for ch in header)
    assert header.startswith('attachment; filename="unicode-.txt"')
    assert "filename*=UTF-8''" in header
    assert "%E2%9C%93" in header


def test_content_disposition_falls_back_to_attachment() -> None:
    """A display name with no printable content degrades to a safe default."""
    assert _content_disposition("\n\r") == 'attachment; filename="attachment"'
    assert _content_disposition("") == 'attachment; filename="attachment"'


def test_missing_filename_error_matches_ava_contract() -> None:
    """The route's own missing-filename error is a 422 AVA ErrorResponse body."""
    response = _missing_file_name()
    assert response.status_code == 422
    payload = response.body.decode()
    assert '"error_code":"missing_file_name"' in payload
    assert '"category":"validation"' in payload


# ============================================================
# END: Content-Disposition Sanitization (white-box)
# ============================================================


# ============================================================
# BEGIN: Route Resolution
# ============================================================


def test_route_shapes_resolve_without_conflicts() -> None:
    """``/content`` resolves to the content handler, never shadowed by metadata."""
    app = make_app()
    insert_record(app, make_record(attachment_id="resolve-1", status=AttachmentStatus.PENDING))
    with TestClient(app) as client:
        metadata = client.get("/attachments/resolve-1")
        content = client.get("/attachments/resolve-1/content")

    assert metadata.status_code == 200
    assert metadata.json()["status"] == "pending"
    assert content.status_code == 409
    assert content.json()["error_code"] == "attachment_content_unavailable"


# ============================================================
# END: Route Resolution
# ============================================================