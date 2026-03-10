from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
from typing import Optional
from uuid import uuid4

from ..contracts import CandidateAtom, WriteAction
from .store import AtomStore


class ProposalStatus(str, Enum):
    """Lifecycle states for queued mutation proposals."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


@dataclass(slots=True)
class MutationProposal:
    """Queued proposal for edit/delete operations requiring approval."""

    proposal_id: str
    action: WriteAction
    target_atom_id: str
    reason_code: str
    created_at: datetime
    status: ProposalStatus = ProposalStatus.PENDING
    replacement_candidate: Optional[CandidateAtom] = None
    retention_days: int = 30
    metadata: dict[str, str] = field(default_factory=dict)
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.action not in {WriteAction.PROPOSE_EDIT, WriteAction.PROPOSE_DELETE}:
            raise ValueError("proposal action must be PROPOSE_EDIT or PROPOSE_DELETE")
        if not self.target_atom_id.strip():
            raise ValueError("target_atom_id is required")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if self.retention_days < 0:
            raise ValueError("retention_days must be >= 0")
        if self.action is WriteAction.PROPOSE_EDIT and self.replacement_candidate is None:
            raise ValueError("replacement_candidate is required for PROPOSE_EDIT")


class MutationReviewQueue:
    """Approval queue for destructive or canonical memory mutations."""

    def __init__(self, store: AtomStore, *, default_retention_days: int = 30) -> None:
        if default_retention_days < 0:
            raise ValueError("default_retention_days must be >= 0")
        self.store = store
        self.default_retention_days = default_retention_days
        self._proposals: dict[str, MutationProposal] = {}
        self._lock = threading.Lock()

    def list_all(self) -> list[MutationProposal]:
        """Return all proposals in insertion order."""

        with self._lock:
            return list(self._proposals.values())

    def list_pending(self) -> list[MutationProposal]:
        """Return pending proposals."""

        with self._lock:
            return [proposal for proposal in self._proposals.values() if proposal.status is ProposalStatus.PENDING]

    def propose_edit(
        self,
        *,
        target_atom_id: str,
        replacement_candidate: CandidateAtom,
        reason_code: str,
        metadata: Optional[dict[str, str]] = None,
    ) -> MutationProposal:
        """Queue an edit proposal that creates a superseding atom after approval."""

        proposal = MutationProposal(
            proposal_id=f"mpr_{uuid4().hex}",
            action=WriteAction.PROPOSE_EDIT,
            target_atom_id=target_atom_id,
            reason_code=reason_code,
            created_at=datetime.now(timezone.utc),
            replacement_candidate=replacement_candidate,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
        return proposal

    def propose_delete(
        self,
        *,
        target_atom_id: str,
        reason_code: str,
        retention_days: Optional[int] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> MutationProposal:
        """Queue a deletion proposal that tombstones atom after approval."""

        proposal = MutationProposal(
            proposal_id=f"mpr_{uuid4().hex}",
            action=WriteAction.PROPOSE_DELETE,
            target_atom_id=target_atom_id,
            reason_code=reason_code,
            created_at=datetime.now(timezone.utc),
            retention_days=self.default_retention_days if retention_days is None else retention_days,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
        return proposal

    def approve(self, proposal_id: str, *, reviewer: str) -> MutationProposal:
        """Approve proposal for later application."""

        with self._lock:
            proposal = self._proposals[proposal_id]
            if proposal.status is not ProposalStatus.PENDING:
                raise ValueError("only pending proposals can be approved")
            proposal.status = ProposalStatus.APPROVED
            proposal.reviewer = reviewer
            proposal.reviewed_at = datetime.now(timezone.utc)
            return proposal

    def reject(self, proposal_id: str, *, reviewer: str, reason: str) -> MutationProposal:
        """Reject proposal and preserve audit context."""

        with self._lock:
            proposal = self._proposals[proposal_id]
            if proposal.status is not ProposalStatus.PENDING:
                raise ValueError("only pending proposals can be rejected")
            proposal.status = ProposalStatus.REJECTED
            proposal.reviewer = reviewer
            proposal.reviewed_at = datetime.now(timezone.utc)
            proposal.metadata["rejection_reason"] = reason
            return proposal

    def apply(self, proposal_id: str) -> MutationProposal:
        """Apply approved proposal to store. Reject unapproved execution."""

        with self._lock:
            proposal = self._proposals[proposal_id]
            if proposal.status is not ProposalStatus.APPROVED:
                raise PermissionError("proposal must be approved before apply")

            if proposal.action is WriteAction.PROPOSE_EDIT:
                assert proposal.replacement_candidate is not None
                self.store.supersede_atom(
                    proposal.target_atom_id,
                    proposal.replacement_candidate,
                    reason=f"proposal:{proposal.proposal_id}",
                )
            elif proposal.action is WriteAction.PROPOSE_DELETE:
                self.store.tombstone_atom(
                    proposal.target_atom_id,
                    reason=f"proposal:{proposal.proposal_id}",
                    retention_days=proposal.retention_days,
                )
            proposal.status = ProposalStatus.APPLIED
            return proposal

    def run_purge(self, *, now: Optional[datetime] = None) -> list[str]:
        """Execute delayed purge for expired tombstones."""

        return self.store.purge_due_atoms(now=now)
