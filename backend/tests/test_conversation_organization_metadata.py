"""Phase 5.42 conversation organization metadata domain tests.

Proves the organization fields added to the canonical conversation domain and
to its public read contract:

* ``is_pinned`` / ``is_archived`` default to ``False`` and ``folder_id`` to
  ``None``, so every pre-existing construction site keeps working unchanged;
* explicitly supplied values round-trip through the record, the service, and
  the public API response;
* the fields are descriptive only — listing stays unfiltered and ordering is
  unchanged, because archiving and sorting are later steps.

No persistence schema, sorting, archive filtering, folder entity, or delete
behavior is exercised or introduced here.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from ava.contracts.conversations import ConversationResponse
from ava.repositories.conversation_repository import ConversationRecord
from ava.services.conversation_service import ConversationService

# ============================================================
# BEGIN: Fixtures
# ============================================================


def _record(**overrides: Any) -> ConversationRecord:
    """A record built the pre-5.42 way unless a field is overridden."""
    now = datetime.now(UTC)
    return ConversationRecord(
        conversation_id="conversation-1",
        title="Original",
        created_at=now,
        updated_at=now,
        **overrides,
    )


# ============================================================
# END: Fixtures
# ============================================================
# BEGIN: Domain defaults
# ============================================================


def test_record_defaults_are_unpinned_unarchived_and_unfiled() -> None:
    """A conversation constructed without organization metadata gets defaults."""
    record = _record()

    assert record.is_pinned is False
    assert record.is_archived is False
    assert record.folder_id is None


def test_explicit_organization_values_are_stored_on_the_record() -> None:
    """Explicitly supplied organization values round-trip on the domain object."""
    record = _record(is_pinned=True, is_archived=True, folder_id="folder-7")

    assert record.is_pinned is True
    assert record.is_archived is True
    assert record.folder_id == "folder-7"


def test_pinned_is_independent_of_archived() -> None:
    """Pin and archive are independent flags, not one combined state."""
    pinned_only = _record(is_pinned=True)
    archived_only = _record(is_archived=True)

    assert (pinned_only.is_pinned, pinned_only.is_archived) == (True, False)
    assert (archived_only.is_pinned, archived_only.is_archived) == (False, True)


def test_replace_preserves_organization_fields() -> None:
    """A later title change keeps organization metadata intact."""
    record = replace(_record(is_pinned=True, folder_id="folder-7"), title="Renamed")

    assert record.title == "Renamed"
    assert record.is_pinned is True
    assert record.folder_id == "folder-7"


# ============================================================
# END: Domain defaults
# ============================================================
# BEGIN: Public contract
# ============================================================


def test_response_defaults_match_the_domain_defaults() -> None:
    """The public response contract defaults identically to the record."""
    response = ConversationResponse(
        conversation_id="conversation-1",
        title="Original",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert response.is_pinned is False
    assert response.is_archived is False
    assert response.folder_id is None


def test_service_maps_organization_fields_onto_the_response() -> None:
    """The record -> response mapping carries all three fields."""

    class StubRepository:
        def __init__(self, record: ConversationRecord) -> None:
            self._record = record

        def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
            return self._record

        def get(self, conversation_id: str) -> ConversationRecord | None:
            return self._record

        def list(self, search: str | None = None) -> list[ConversationRecord]:
            return [self._record]

        def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
            return self._record

        def update_content(
            self, conversation_id: str, message_id: str, *, content: str, status: Any = None
        ) -> Any:
            return None

        def append(
            self,
            conversation_id: str,
            *,
            message_id: str,
            role: Any,
            content: str,
            source_run_id: str | None = None,
            created_at: Any = None,
        ) -> Any:
            return self._record

    service = ConversationService(
        conversation_repository=StubRepository(_record(is_pinned=True, folder_id="folder-7")),  # type: ignore[arg-type]
        message_repository=StubRepository(_record()),  # type: ignore[arg-type]
    )
    response = service.get_conversation("conversation-1")

    assert response is not None
    assert response.is_pinned is True
    assert response.is_archived is False
    assert response.folder_id == "folder-7"


# ============================================================
# END: Public contract
# ============================================================
# BEGIN: API surface
# ============================================================


def _api_client() -> TestClient:
    from ava.api.app import create_app

    return TestClient(create_app())


def test_create_exposes_organization_defaults_over_http() -> None:
    """A freshly created conversation reports the default organization state."""
    with _api_client() as client:
        response = client.post("/conversations", json={"title": "Organized"})

    assert response.status_code == 201
    body = response.json()
    assert body["is_pinned"] is False
    assert body["is_archived"] is False
    assert body["folder_id"] is None


def test_get_and_list_expose_organization_fields() -> None:
    """Reads surface the fields, and listing still includes every conversation."""
    with _api_client() as client:
        first = client.post("/conversations", json={"title": "First"}).json()
        second = client.post("/conversations", json={"title": "Second"}).json()

        single = client.get(f"/conversations/{first['conversation_id']}")
        listing = client.get("/conversations")

    assert single.status_code == 200
    for body in (single.json(), *(item for item in listing.json()["conversations"])):
        assert set(body) >= {"is_pinned", "is_archived", "folder_id"}
        assert body["is_pinned"] is False
        assert body["is_archived"] is False
        assert body["folder_id"] is None

    # Listing remains unfiltered; canonical sorting is specified separately.
    expected = sorted(
        [first, second], key=lambda item: item["conversation_id"]
    )
    expected.sort(
        key=lambda item: (item["is_pinned"], item["updated_at"], item["created_at"]),
        reverse=True,
    )
    assert [item["conversation_id"] for item in listing.json()["conversations"]] == [
        item["conversation_id"] for item in expected
    ]


def test_rename_does_not_disturb_organization_fields() -> None:
    """Renaming still works and still reports the organization defaults."""
    with _api_client() as client:
        created = client.post("/conversations", json={"title": "Before"}).json()
        renamed = client.patch(
            f"/conversations/{created['conversation_id']}",
            json={"title": "After"},
        )

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "After"
    assert renamed.json()["is_pinned"] is False
    assert renamed.json()["is_archived"] is False
    assert renamed.json()["folder_id"] is None


def test_rename_route_does_not_write_organization_metadata() -> None:
    """The rename route stays title-only; Phase 5.44 uses a separate pin route."""
    with _api_client() as client:
        created = client.post("/conversations", json={"title": "Read Only"}).json()
        conversation_id = created["conversation_id"]

        # The rename contract still requires a title, so an organization-only
        # body is rejected exactly as it was before 5.42.
        rejected = client.patch(
            f"/conversations/{conversation_id}",
            json={"is_pinned": True, "is_archived": True, "folder_id": "folder-1"},
        )

        # When a valid rename is sent alongside organization fields, the extra
        # fields are ignored rather than applied by the rename route.
        renamed = client.patch(
            f"/conversations/{conversation_id}",
            json={
                "title": "Renamed",
                "is_pinned": True,
                "is_archived": True,
                "folder_id": "folder-1",
            },
        )

    assert rejected.status_code == 422
    assert renamed.status_code == 200
    body = renamed.json()
    assert body["is_pinned"] is False
    assert body["is_archived"] is False
    assert body["folder_id"] is None


# ============================================================
# END: API surface
# ============================================================
