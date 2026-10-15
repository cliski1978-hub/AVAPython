"""Explicit server-configured Workspace administration policy.

The policy is provisioning metadata, never an HTTP claim. Missing configuration
denies every action; operators may inject it only in trusted composition.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256

from ava.contracts.approvals import ApprovalDecisionAuthorityPort, ApprovalHumanAuthority, ApprovalRecord
from ava.contracts.security_identity import PrincipalActorType, VerifiedPrincipal
from ava.contracts.workspace_grants import WorkspaceGrantAdministrationPort


@dataclass(frozen=True)
class _AdministratorScope:
    workspace_id: str
    tenant_ref: str | None
    principal_refs: frozenset[str]


class ConfiguredWorkspaceGrantAdministration(WorkspaceGrantAdministrationPort):
    """Allow only explicitly provisioned human principal refs per tenant/Workspace."""

    _ACTIONS = frozenset({"list", "create", "update", "revoke", "approve"})

    def __init__(self, scopes: tuple[_AdministratorScope, ...] = ()) -> None:
        normalized = tuple(sorted(scopes, key=lambda scope: (scope.workspace_id, scope.tenant_ref or "")))
        self._scopes = normalized
        self.revision_ref = sha256(
            json.dumps(
                [
                    {
                        "workspace_id": scope.workspace_id,
                        "tenant_ref": scope.tenant_ref,
                        "principal_refs": sorted(scope.principal_refs),
                    }
                    for scope in normalized
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @classmethod
    def from_environment(cls) -> ConfiguredWorkspaceGrantAdministration:
        """Load explicit admin scopes from AVA_WORKSPACE_GRANT_ADMIN_POLICY."""
        raw = os.environ.get("AVA_WORKSPACE_GRANT_ADMIN_POLICY")
        if not raw:
            return cls()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError
            scopes = []
            for item in payload:
                if not isinstance(item, dict) or set(item) != {"workspace_id", "tenant_ref", "principal_refs"}:
                    raise ValueError
                workspace_id = item["workspace_id"]
                tenant_ref = item["tenant_ref"]
                principal_refs = item["principal_refs"]
                if (
                    not isinstance(workspace_id, str) or not workspace_id
                    or (tenant_ref is not None and (not isinstance(tenant_ref, str) or not tenant_ref))
                    or not isinstance(principal_refs, list) or not principal_refs
                    or any(
                        not isinstance(ref, str) or len(ref) != 64
                        or any(char not in "0123456789abcdef" for char in ref)
                        for ref in principal_refs
                    )
                    or len(set(principal_refs)) != len(principal_refs)
                ):
                    raise ValueError
                scopes.append(_AdministratorScope(workspace_id, tenant_ref, frozenset(principal_refs)))
            if len({(scope.workspace_id, scope.tenant_ref) for scope in scopes}) != len(scopes):
                raise ValueError
            return cls(tuple(scopes))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Workspace grant administration policy is invalid.") from exc

    def can_manage(
        self, principal: VerifiedPrincipal, *, workspace_id: str, action: str
    ) -> bool:
        if action not in self._ACTIONS or principal.actor_type != PrincipalActorType.HUMAN:
            return False
        return any(
            scope.workspace_id == workspace_id
            and scope.tenant_ref == principal.tenant_ref
            and principal.principal_ref in scope.principal_refs
            for scope in self._scopes
        )


class WorkspaceAdminApprovalDecisionAuthority(ApprovalDecisionAuthorityPort):
    """Use the configured Workspace admin boundary for human approval decisions."""

    def __init__(self, administration: WorkspaceGrantAdministrationPort) -> None:
        self._administration = administration
        self._revision_ref = getattr(administration, "revision_ref", "server-managed-workspace-admin-policy")

    def resolve_for(
        self, approval: ApprovalRecord, principal: VerifiedPrincipal | None = None
    ) -> ApprovalHumanAuthority | None:
        if principal is None or not self._administration.can_manage(
            principal, workspace_id=approval.workspace_id, action="approve"
        ):
            return None
        authority_revision_ref = sha256(
            "\0".join(
                (
                    principal.principal_ref,
                    principal.authentication_context_ref,
                    approval.workspace_id,
                    self._revision_ref,
                )
            ).encode()
        ).hexdigest()
        return ApprovalHumanAuthority(
            principal_ref=principal.principal_ref,
            authority_revision_ref=authority_revision_ref,
            workspace_ids=frozenset({approval.workspace_id}),
            can_decide=True,
        )
