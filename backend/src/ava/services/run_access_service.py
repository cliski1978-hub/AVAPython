"""Run resource authorization over trusted identity and durable ownership."""

from ava.contracts.security_identity import VerifiedPrincipal
from ava.repositories.run_repository import RunRecord, RunRepository


class RunAccessService:
    """Enforce exact principal and tenant ownership, hiding foreign Runs as absent."""

    def __init__(self, runs: RunRepository) -> None:
        self._runs = runs

    @staticmethod
    def owns(record: RunRecord, principal: VerifiedPrincipal) -> bool:
        return (
            record.owner_principal_ref is not None
            and record.owner_principal_ref == principal.principal_ref
            and record.owner_tenant_ref == principal.tenant_ref
        )

    def get_authorized(self, run_id: str, principal: VerifiedPrincipal) -> RunRecord | None:
        record = self._runs.get(run_id)
        return record if record is not None and self.owns(record, principal) else None

    def list_for_conversation(self, conversation_id: str, principal: VerifiedPrincipal) -> list[RunRecord]:
        # Filter before projection so run IDs and metadata for foreign records
        # never cross the API boundary. Ownerless historical Runs stay quarantined.
        return [record for record in self._runs.list_for_conversation(conversation_id) if self.owns(record, principal)]
