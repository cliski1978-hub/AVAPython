"""Document API tests (Step 4.5).

API-level coverage for the document transport layer: creating, reading,
renaming, updating content, and listing documents through ``/documents``.
The routes must operate on AVA-owned contracts, delegate to
``DocumentService``, and never expose internal identifiers from clients.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Helpers
# ============================================================


def make_client() -> TestClient:
    """Create a test client with a default application."""
    return TestClient(create_app())


def create_document(
    client: TestClient,
    *,
    title: str | None = None,
    content: str = "<p>body</p>",
) -> dict[str, Any]:
    """Create a document and return the parsed 201 response body."""
    payload: dict[str, str] = {"content": content}
    if title is not None:
        payload["title"] = title
    response = client.post("/documents", json=payload)
    assert response.status_code == 201
    return dict(response.json())


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Create Document
# ============================================================


def test_create_document_returns_201_and_response_shape() -> None:
    """A valid document create should return 201 with the response contract."""
    with make_client() as client:
        body = create_document(client, title="My Doc")

    assert set(body) == {
        "document_id",
        "title",
        "content",
        "content_format",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert body["title"] == "My Doc"
    assert body["content"] == "<p>body</p>"
    assert body["content_format"] == "html"
    assert body["contract_version"] == CONTRACT_VERSION


def test_create_document_defaults_title() -> None:
    """An omitted title resolves to the service default."""
    with make_client() as client:
        body = create_document(client)
    assert body["title"] == "Untitled Document"


def test_create_document_mints_valid_ava_owned_uuid() -> None:
    """The document identifier is a service-generated UUID."""
    with make_client() as client:
        body = create_document(client)
    document_id = body["document_id"]
    assert UUID(document_id)
    assert str(UUID(document_id)) == document_id


def test_create_document_timestamps_are_utc_iso() -> None:
    """Timestamps serialize as timezone-aware ISO strings."""
    with make_client() as client:
        body = create_document(client)
    for raw in (body["created_at"], body["updated_at"]):
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() is not None
        assert parsed.utcoffset().total_seconds() == UTC.utcoffset(None).total_seconds()


def test_create_document_rejects_dangerous_content_with_422() -> None:
    """Executable markup is rejected at the API, never stored."""
    for content in (
        "<script>alert(1)</script>",
        "<p onclick='x()'>y</p>",
        '<a href="javascript:alert(1)">x</a>',
    ):
        with make_client() as client:
            response = client.post("/documents", json={"content": content})
        assert response.status_code == 422
        body = dict(response.json())
        assert body["error_code"] == "invalid_document_content"
        assert body["category"] == "validation"


def test_create_document_rejects_blank_or_missing_content_with_422() -> None:
    """Contract validation rejects empty/blank/missing content."""
    for payload in ({}, {"content": ""}, {"content": "   "}):
        with make_client() as client:
            response = client.post("/documents", json=payload)
        assert response.status_code == 422


def test_create_document_rejects_unsupported_content_format_with_422() -> None:
    """Only the AVA-owned ``html`` format is accepted today."""
    with make_client() as client:
        response = client.post("/documents", json={"content": "<p>x</p>", "content_format": "markdown"})
    assert response.status_code == 422


def test_create_document_duplicate_maps_to_409() -> None:
    """A duplicate document identifier collision maps to 409."""
    from datetime import datetime

    from ava.repositories import DocumentRecord
    from ava.services.document_revision_store import InMemoryDocumentRevisionStore
    from ava.services.document_service import DocumentService
    from ava.services.document_store import DocumentStore

    class AlwaysDuplicate:
        """Write-coordinator double whose create always reports a duplicate id."""

        def create(
            self,
            document: DocumentRecord,
            *,
            revision_id: str,
            revision_created_at: datetime,
        ) -> tuple[DocumentRecord, object]:
            raise ValueError(f"Document already exists: {document.document_id}")

        def update(
            self,
            document: DocumentRecord,
            *,
            revision_id: str,
            revision_created_at: datetime,
        ) -> tuple[DocumentRecord, object]:
            raise ValueError(f"Document already exists: {document.document_id}")

    app = create_app()
    app.state.document_service = DocumentService(
        document_repository=DocumentStore(),
        document_revision_repository=InMemoryDocumentRevisionStore(),
        document_write_coordinator=AlwaysDuplicate(),
    )
    with TestClient(app) as client:
        response = client.post("/documents", json={"content": "<p>body</p>"})
    assert response.status_code == 409
    body = dict(response.json())
    assert body["error_code"] == "document_id_conflict"
    assert body["category"] == "validation"


# ============================================================
# END: Create Document
# ============================================================


# ============================================================
# BEGIN: List Documents
# ============================================================


def test_list_documents_is_empty_until_a_create() -> None:
    with make_client() as client:
        response = client.get("/documents")
    assert response.status_code == 200
    assert response.json() == {"contract_version": CONTRACT_VERSION, "documents": []}


def test_list_documents_in_insertion_order() -> None:
    with make_client() as client:
        first = create_document(client, title="First")
        create_document(client, title="Second")
        response = client.get("/documents")

    assert response.status_code == 200
    body = dict(response.json())
    assert [c["title"] for c in body["documents"]] == ["First", "Second"]
    assert body["documents"][0]["document_id"] == first["document_id"]


# ============================================================
# END: List Documents
# ============================================================


# ============================================================
# BEGIN: Get Document
# ============================================================


def test_get_document_returns_existing_document() -> None:
    with make_client() as client:
        created = create_document(client, title="My Doc", content="<p>hello</p>")
        response = client.get(f'/documents/{created["document_id"]}')

    assert response.status_code == 200
    body = dict(response.json())
    assert body["document_id"] == created["document_id"]
    assert body["title"] == "My Doc"
    assert body["content"] == "<p>hello</p>"


def test_get_document_unknown_maps_to_404() -> None:
    with make_client() as client:
        response = client.get("/documents/missing")

    assert response.status_code == 404
    body = dict(response.json())
    assert body["error_code"] == "document_not_found"
    assert body["category"] == "not_found"


# ============================================================
# END: Get Document
# ============================================================


# ============================================================
# BEGIN: Update Document
# ============================================================


def test_patch_document_renames_title() -> None:
    with make_client() as client:
        created = create_document(client, title="Before")
        response = client.patch(
            f'/documents/{created["document_id"]}', json={"title": "  After  "}
        )

    assert response.status_code == 200
    body = dict(response.json())
    assert body["title"] == "After"
    assert body["content"] == "<p>body</p>"


def test_patch_document_updates_content() -> None:
    with make_client() as client:
        created = create_document(client, content="<p>old</p>")
        response = client.patch(
            f'/documents/{created["document_id"]}', json={"content": "<h2>new</h2>"}
        )

    assert response.status_code == 200
    body = dict(response.json())
    assert body["content"] == "<h2>new</h2>"
    assert body["content_format"] == "html"
    assert body["title"] == "Untitled Document"


def test_patch_document_applies_title_then_content() -> None:
    """With both fields present the title lands first (content is final state)."""
    with make_client() as client:
        created = create_document(client, title="Before", content="<p>old</p>")
        response = client.patch(
            f'/documents/{created["document_id"]}',
            json={"title": "After", "content": "<p>new</p>"},
        )

    assert response.status_code == 200
    body = dict(response.json())
    assert body["title"] == "After"
    assert body["content"] == "<p>new</p>"


def test_patch_document_unknown_maps_to_404() -> None:
    with make_client() as client:
        response = client.patch(
            "/documents/missing", json={"title": "New Title"}
        )
    assert response.status_code == 404
    body = dict(response.json())
    assert body["error_code"] == "document_not_found"


def test_patch_document_unknown_wins_over_invalid_content() -> None:
    """An unknown document returns 404 even with a policy-violating payload."""
    with make_client() as client:
        response = client.patch(
            "/documents/missing", json={"content": "<script>alert(1)</script>"}
        )
    assert response.status_code == 404
    assert dict(response.json())["error_code"] == "document_not_found"


def test_patch_document_rejects_dangerous_content_with_422() -> None:
    with make_client() as client:
        created = create_document(client, content="<p>safe</p>")
        response = client.patch(
            f'/documents/{created["document_id"]}',
            json={"content": "<img src=x onerror=alert(1)>"},
        )
    assert response.status_code == 422
    body = dict(response.json())
    assert body["error_code"] == "invalid_document_content"


def test_patch_document_contract_rejects_empty_and_blank_updates() -> None:
    """An update must carry at least one field, and fields must be non-blank."""
    with make_client() as client:
        created = create_document(client, title="Before")

        empty = client.patch(f'/documents/{created["document_id"]}', json={})
        blank_title = client.patch(f'/documents/{created["document_id"]}', json={"title": "   "})
        blank_content = client.patch(
            f'/documents/{created["document_id"]}', json={"content": ""}
        )

    assert empty.status_code == 422
    assert blank_title.status_code == 422
    assert blank_content.status_code == 422


def test_patch_document_rejects_unsupported_content_format_with_422() -> None:
    with make_client() as client:
        created = create_document(client, content="<p>safe</p>")
        response = client.patch(
            f'/documents/{created["document_id"]}',
            json={"content": "<p>new</p>", "content_format": "markdown"},
        )
    assert response.status_code == 422


# ============================================================
# END: Update Document
# ============================================================


# ============================================================
# BEGIN: Revision History Through Writes (Step 4.13.D)
# ============================================================


def revision_count(client: TestClient, document_id: str) -> int:
    """Return the document's revision history length through the composed app."""
    revisions = client.app.state.persistence.document_revision_repository
    return len(revisions.list_for_document(document_id))


def latest_revision(client: TestClient, document_id: str):
    """Return the document's most recent revision through the composed app."""
    revisions = client.app.state.persistence.document_revision_repository
    return revisions.get_latest(document_id)


def test_post_creates_one_revision_against_the_returned_state() -> None:
    """POST now also writes revision 1; the response shape is unchanged."""
    with make_client() as client:
        created = create_document(client, title="My Doc", content="<p>body</p>")

        assert revision_count(client, created["document_id"]) == 1
        revision = latest_revision(client, created["document_id"])
        assert revision is not None
        assert revision.revision_number == 1
        assert revision.title == created["title"]
        assert revision.content == created["content"]
        assert revision.content_format == created["content_format"]

        response = client.get(f'/documents/{created["document_id"]}')
        body = dict(response.json())
        assert body == created


def test_patch_title_only_appends_exactly_one_revision() -> None:
    with make_client() as client:
        created = create_document(client, title="Before")
        document_id = created["document_id"]
        assert revision_count(client, document_id) == 1

        response = client.patch(f"/documents/{document_id}", json={"title": "After"})

        assert response.status_code == 200
        body = dict(response.json())
        assert body == client.get(f"/documents/{document_id}").json()
        assert revision_count(client, document_id) == 2
        revision = latest_revision(client, document_id)
        assert revision is not None
        assert revision.revision_number == 2
        assert revision.title == "After"
        assert revision.content == created["content"]


def test_patch_content_only_appends_exactly_one_revision() -> None:
    with make_client() as client:
        created = create_document(client, content="<p>old</p>")
        document_id = created["document_id"]

        response = client.patch(
            f"/documents/{document_id}", json={"content": "<h2>new</h2>"}
        )

        assert response.status_code == 200
        body = dict(response.json())
        assert revision_count(client, document_id) == 2
        revision = latest_revision(client, document_id)
        assert revision is not None
        assert revision.revision_number == 2
        assert revision.title == created["title"]
        assert revision.content == "<h2>new</h2>"
        assert revision.title == body["title"]
        assert revision.content == body["content"]


def test_patch_title_and_content_appends_exactly_one_revision() -> None:
    """A combined title+content PATCH is coalesced into a single revision."""
    with make_client() as client:
        created = create_document(client, title="Old", content="<p>old</p>")
        document_id = created["document_id"]

        response = client.patch(
            f"/documents/{document_id}",
            json={"title": "New Title", "content": "<p>new</p>"},
        )

        assert response.status_code == 200
        body = dict(response.json())
        assert revision_count(client, document_id) == 2
        revision = latest_revision(client, document_id)
        assert revision is not None
        assert revision.revision_number == 2
        assert revision.title == "New Title"
        assert revision.content == "<p>new</p>"
        assert revision.title == body["title"]
        assert revision.content == body["content"]


def test_patch_revision_snapshot_matches_the_returned_current_state() -> None:
    """The appended revision is a full snapshot of the final current document."""
    with make_client() as client:
        created = create_document(client, title="Before", content="<p>first</p>")
        document_id = created["document_id"]

        updated = client.patch(
            f"/documents/{document_id}",
            json={"title": "After", "content": "<p>final</p>"},
        ).json()

        revision = latest_revision(client, document_id)
        assert revision is not None
        assert (revision.title, revision.content) == (
            updated["title"],
            updated["content"],
        )
        listed = client.app.state.persistence.document_revision_repository.list_for_document(
            document_id
        )
        assert [record.revision_number for record in listed] == [1, 2]


def test_failed_patch_appends_no_revision() -> None:
    """A policy-rejected PATCH leaves current state and history untouched."""
    with make_client() as client:
        created = create_document(client, content="<p>safe</p>")
        document_id = created["document_id"]

        response = client.patch(
            f"/documents/{document_id}",
            json={"content": "<img src=x onerror=alert(1)>"},
        )

        assert response.status_code == 422
        assert revision_count(client, document_id) == 1
        current = client.get(f"/documents/{document_id}").json()
        assert current["content"] == "<p>safe</p>"


# ============================================================
# END: Revision History Through Writes (Step 4.13.D)
# ============================================================


# ============================================================
# BEGIN: Revision History Routes (Step 4.13.E)
# ============================================================


def test_revision_history_route_lists_ordered_snapshots() -> None:
    """POST + two PATCHes yields revisions [1, 2, 3] in revision-number order."""
    with make_client() as client:
        created = create_document(client, title="First", content="<p>one</p>")
        document_id = created["document_id"]
        client.patch(f"/documents/{document_id}", json={"title": "Second", "content": "<p>two</p>"})
        client.patch(f"/documents/{document_id}", json={"title": "Third", "content": "<p>three</p>"})

        response = client.get(f"/documents/{document_id}/revisions")

        assert response.status_code == 200
        body = dict(response.json())
        assert body["document_id"] == document_id
        assert body["contract_version"] == CONTRACT_VERSION
        revisions = body["revisions"]
        assert [revision["revision_number"] for revision in revisions] == [1, 2, 3]
        assert [revision["title"] for revision in revisions] == ["First", "Second", "Third"]
        assert [revision["content"] for revision in revisions] == [
            "<p>one</p>",
            "<p>two</p>",
            "<p>three</p>",
        ]
        assert all(revision["document_id"] == document_id for revision in revisions)
        assert all(revision["contract_version"] == CONTRACT_VERSION for revision in revisions)
        for revision in revisions:
            assert revision["content_format"] == "html"
            assert datetime.fromisoformat(revision["created_at"]).utcoffset() is not None


def test_revision_history_route_latest_matches_current_state() -> None:
    """The newest revision snapshot equals GET /documents/{id}."""
    with make_client() as client:
        created = create_document(client, title="Before", content="<p>old</p>")
        document_id = created["document_id"]
        updated = client.patch(
            f"/documents/{document_id}", json={"title": "After", "content": "<p>new</p>"}
        ).json()

        history = client.get(f"/documents/{document_id}/revisions").json()["revisions"]
        latest = history[-1]
        assert (latest["title"], latest["content"]) == (updated["title"], updated["content"])


def test_revision_history_route_exact_revision() -> None:
    """GET /documents/{id}/revisions/{revision_id} returns the exact revision."""
    with make_client() as client:
        created = create_document(client, title="First", content="<p>version one</p>")
        document_id = created["document_id"]
        client.patch(
            f"/documents/{document_id}", json={"title": "Second", "content": "<h2>version two</h2>"}
        )

        history = client.get(f"/documents/{document_id}/revisions").json()["revisions"]
        first, second = history

        first_response = client.get(f"/documents/{document_id}/revisions/{first['revision_id']}")
        second_response = client.get(f"/documents/{document_id}/revisions/{second['revision_id']}")

        assert first_response.status_code == 200
        first_body = dict(first_response.json())
        assert first_body == first
        assert first_body["revision_number"] == 1
        assert first_body["title"] == "First"
        assert first_body["content"] == "<p>version one</p>"
        assert first_body["content_format"] == "html"
        assert datetime.fromisoformat(first_body["created_at"]).utcoffset() is not None

        assert second_response.status_code == 200
        second_body = dict(second_response.json())
        assert second_body == second
        assert second_body["revision_number"] == 2
        assert second_body["title"] == "Second"
        assert second_body["content"] == "<h2>version two</h2>"


def test_revision_history_route_unknown_document_maps_to_404() -> None:
    """Both revision routes preserve the established document_not_found shape."""
    for path in (
        "/documents/missing/revisions",
        "/documents/missing/revisions/revision-x",
    ):
        with make_client() as client:
            response = client.get(path)
        assert response.status_code == 404
        body = dict(response.json())
        assert body["error_code"] == "document_not_found"
        assert body["category"] == "not_found"


def test_revision_history_route_unknown_revision_maps_to_404() -> None:
    """Known document + unknown revision → 404, same error body shape."""
    with make_client() as client:
        created = create_document(client, content="<p>body</p>")
        response = client.get(f'/documents/{created["document_id"]}/revisions/missing-revision')

    assert response.status_code == 404
    body = dict(response.json())
    assert body["error_code"] == "document_not_found"
    assert body["category"] == "not_found"


def test_revision_history_route_cross_document_revision_maps_to_404() -> None:
    """A revision from document A never resolves through document B."""
    with make_client() as client:
        document_a = create_document(client, title="A", content="<p>from a</p>")
        document_b = create_document(client, title="B", content="<p>from b</p>")
        revision_a = client.get(f'/documents/{document_a["document_id"]}/revisions').json()["revisions"][0]

        response = client.get(
            f'/documents/{document_b["document_id"]}/revisions/{revision_a["revision_id"]}'
        )

    assert response.status_code == 404
    body = dict(response.json())
    assert body["error_code"] == "document_not_found"


def test_known_document_with_no_history_returns_empty_list() -> None:
    """A legacy known document returns 200 with revisions [] (≠ unknown 404)."""
    import sqlite3
    import tempfile
    from pathlib import Path

    from ava.configuration.settings import Settings
    from ava.infrastructure.persistence.migrations.versions.v0001_initial_schema import migrate_up

    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    try:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        migrate_up(connection)
        connection.execute(
            "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "legacy-route",
                "Legacy",
                "<p>pre history</p>",
                "html",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
        connection.close()

        app = create_app(
            settings=Settings(
                persistence_provider="relational",
                persistence_database_url=str(path),
            )
        )
        with TestClient(app) as client:
            response = client.get("/documents/legacy-route/revisions")

        assert response.status_code == 200
        body = dict(response.json())
        assert body["document_id"] == "legacy-route"
        assert body["revisions"] == []
        assert body["contract_version"] == CONTRACT_VERSION
    finally:
        if path.exists():
            path.unlink()


def test_revision_route_shape_does_not_conflict_with_document_routes() -> None:
    """The history paths and /documents/{id} resolve independently."""
    with make_client() as client:
        created = create_document(client, content="<p>body</p>")
        document_id = created["document_id"]

        history = client.get(f"/documents/{document_id}/revisions")
        current = client.get(f"/documents/{document_id}")
        exact = client.get(f"/documents/{document_id}/revisions/{created['document_id']}")

    assert history.status_code == 200
    assert current.status_code == 200
    assert current.json() == created
    # An unknown revision id returns 404, not the document.
    assert exact.status_code == 404


# ============================================================
# END: Revision History Routes (Step 4.13.E)
# ============================================================