from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import threading
from typing import Callable, Optional
from uuid import uuid4

from ..contracts import AtomType, CandidateAtom, WriteAction, contract_to_dict, source_ref_from_dict
from .sqlite_store import SqliteAtomStore
from .store import AtomStore


class ProposalStatus(str, Enum):
    """Lifecycle states for queued mutation proposals."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class DecisionConflictError(ValueError):
    """A reviewer attempted an opposite immutable decision."""

    code = "DECISION_CONFLICT"


@dataclass(slots=True)
class MutationProposal:
    """Queued proposal for reviewer-controlled evidence-atom mutations."""

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
    created_by: Optional[str] = None
    applied_atom_id: Optional[str] = None
    apply_identity: Optional[str] = None
    applied_at: Optional[datetime] = None
    refresh_pending: bool = False

    def __post_init__(self) -> None:
        if self.action not in {WriteAction.PROPOSE_CREATE, WriteAction.PROPOSE_EDIT, WriteAction.PROPOSE_DELETE}:
            raise ValueError("proposal action must be PROPOSE_CREATE, PROPOSE_EDIT, or PROPOSE_DELETE")
        if self.action is not WriteAction.PROPOSE_CREATE and not self.target_atom_id.strip():
            raise ValueError("target_atom_id is required")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if self.retention_days < 0:
            raise ValueError("retention_days must be >= 0")
        if self.action in {WriteAction.PROPOSE_CREATE, WriteAction.PROPOSE_EDIT} and self.replacement_candidate is None:
            raise ValueError("replacement_candidate is required for PROPOSE_CREATE/PROPOSE_EDIT")


class MutationReviewQueue:
    """Reviewer-controlled queue; SQLite stores are durable, in-memory stores remain dev/test only."""

    def __init__(self, store: AtomStore | SqliteAtomStore, *, default_retention_days: int = 30) -> None:
        if default_retention_days < 0:
            raise ValueError("default_retention_days must be >= 0")
        self.store = store
        self.default_retention_days = default_retention_days
        self._proposals: dict[str, MutationProposal] = {}
        self._lock = threading.Lock()

    @property
    def _durable(self) -> bool:
        return isinstance(self.store, SqliteAtomStore)

    def list_all(self) -> list[MutationProposal]:
        if self._durable:
            assert isinstance(self.store, SqliteAtomStore)
            return [self._from_sqlite(row) for row in self.store.mutation_review_list()]
        with self._lock:
            return list(self._proposals.values())

    def list_pending(self) -> list[MutationProposal]:
        return [proposal for proposal in self.list_all() if proposal.status is ProposalStatus.PENDING]

    def get(self, proposal_id: str) -> MutationProposal:
        if self._durable:
            assert isinstance(self.store, SqliteAtomStore)
            return self._from_sqlite(self.store.mutation_review_get(proposal_id))
        with self._lock:
            return self._proposals[proposal_id]

    def propose_edit(
        self,
        *,
        target_atom_id: str,
        replacement_candidate: CandidateAtom,
        reason_code: str,
        metadata: Optional[dict[str, str]] = None,
        actor: Optional[str] = None,
    ) -> MutationProposal:
        return self._propose(
            action=WriteAction.PROPOSE_EDIT,
            target_atom_id=target_atom_id,
            replacement_candidate=replacement_candidate,
            reason_code=reason_code,
            metadata=metadata,
            actor=actor,
        )

    def propose_create(
        self,
        *,
        candidate: CandidateAtom,
        reason_code: str,
        metadata: Optional[dict[str, str]] = None,
        actor: Optional[str] = None,
    ) -> MutationProposal:
        return self._propose(
            action=WriteAction.PROPOSE_CREATE,
            target_atom_id="",
            replacement_candidate=candidate,
            reason_code=reason_code,
            metadata=metadata,
            actor=actor,
        )

    def propose_delete(
        self,
        *,
        target_atom_id: str,
        reason_code: str,
        retention_days: Optional[int] = None,
        metadata: Optional[dict[str, str]] = None,
        actor: Optional[str] = None,
    ) -> MutationProposal:
        return self._propose(
            action=WriteAction.PROPOSE_DELETE,
            target_atom_id=target_atom_id,
            replacement_candidate=None,
            reason_code=reason_code,
            retention_days=self.default_retention_days if retention_days is None else retention_days,
            metadata=metadata,
            actor=actor,
        )

    def _propose(
        self,
        *,
        action: WriteAction,
        target_atom_id: str,
        replacement_candidate: CandidateAtom | None,
        reason_code: str,
        retention_days: int = 30,
        metadata: Optional[dict[str, str]],
        actor: Optional[str],
    ) -> MutationProposal:
        proposal = MutationProposal(
            proposal_id=f"mpr_{uuid4().hex}",
            action=action,
            target_atom_id=target_atom_id,
            reason_code=reason_code,
            created_at=datetime.now(timezone.utc),
            replacement_candidate=replacement_candidate,
            retention_days=retention_days,
            metadata=dict(metadata or {}),
            created_by=self._optional_actor(actor),
        )
        if self._durable:
            assert isinstance(self.store, SqliteAtomStore)
            return self._from_sqlite(self.store.mutation_review_create(self._to_sqlite(proposal)))
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
        return proposal

    def approve(
        self, proposal_id: str, *, reviewer: Optional[str] = None, actor: Optional[str] = None
    ) -> MutationProposal:
        return self.resolve(proposal_id, decision="approve", actor=self._actor(actor, reviewer))

    def reject(
        self,
        proposal_id: str,
        *,
        reviewer: Optional[str] = None,
        actor: Optional[str] = None,
        reason: str,
    ) -> MutationProposal:
        return self.resolve(proposal_id, decision="reject", actor=self._actor(actor, reviewer), reason=reason)

    def resolve(
        self,
        proposal_id: str,
        *,
        decision: str,
        actor: str,
        apply: bool = False,
        reason: str = "",
        refresh_cache: Callable[[], None] | None = None,
    ) -> MutationProposal:
        """Resolve with authenticated actor identity; a later server layer owns authorization."""

        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if apply and decision != "approve":
            raise ValueError("reject decisions cannot apply")
        if self._durable:
            assert isinstance(self.store, SqliteAtomStore)
            result = self.store.mutation_review_resolve(
                proposal_id, decision=decision, actor_id=self._actor(actor), rejection_reason=reason, apply=apply
            )
            if "decision_conflict" in result:
                raise DecisionConflictError(
                    f"DECISION_CONFLICT: proposal already {result['decision_conflict']}d"
                )
            proposal = self._from_sqlite(result["proposal"])
            if apply and refresh_cache is not None:
                try:
                    refresh_cache()
                except Exception:
                    self.store.mutation_review_mark_refresh_pending(proposal_id)
                    proposal = self.get(proposal_id)
            return proposal

        with self._lock:
            proposal = self._proposals[proposal_id]
            current_decision = "approve" if proposal.status in {ProposalStatus.APPROVED, ProposalStatus.APPLIED} else "reject" if proposal.status is ProposalStatus.REJECTED else ""
            if current_decision and current_decision != decision:
                raise DecisionConflictError(f"DECISION_CONFLICT: proposal already {current_decision}d")
            if proposal.status is ProposalStatus.PENDING:
                proposal.status = ProposalStatus.APPROVED if decision == "approve" else ProposalStatus.REJECTED
                proposal.reviewer = self._actor(actor)
                proposal.reviewed_at = datetime.now(timezone.utc)
                if decision == "reject":
                    proposal.metadata["rejection_reason"] = reason
            if apply:
                self._apply_in_memory(proposal)
            return proposal

    def apply(
        self,
        proposal_id: str,
        *,
        actor: Optional[str] = None,
        refresh_cache: Callable[[], None] | None = None,
    ) -> MutationProposal:
        proposal = self.get(proposal_id)
        if proposal.status not in {ProposalStatus.APPROVED, ProposalStatus.APPLIED}:
            raise PermissionError("proposal must be approved before apply")
        effective_actor = self._actor(actor or proposal.reviewer or "legacy-apply")
        return self.resolve(
            proposal_id, decision="approve", actor=effective_actor, apply=True, refresh_cache=refresh_cache
        )

    def _apply_in_memory(self, proposal: MutationProposal) -> None:
        if proposal.status is ProposalStatus.APPLIED:
            return
        if proposal.status is not ProposalStatus.APPROVED:
            raise PermissionError("proposal must be approved before apply")
        if proposal.action is WriteAction.PROPOSE_CREATE:
            assert proposal.replacement_candidate is not None
            atom = self.store.add_candidate(proposal.replacement_candidate, reason=f"proposal:{proposal.proposal_id}")
        elif proposal.action is WriteAction.PROPOSE_EDIT:
            assert proposal.replacement_candidate is not None
            atom = self.store.supersede_atom(
                proposal.target_atom_id, proposal.replacement_candidate, reason=f"proposal:{proposal.proposal_id}"
            )
        else:
            atom = self.store.tombstone_atom(
                proposal.target_atom_id, reason=f"proposal:{proposal.proposal_id}", retention_days=proposal.retention_days
            )
        proposal.status = ProposalStatus.APPLIED
        proposal.applied_atom_id = atom.atom_id
        proposal.applied_at = datetime.now(timezone.utc)

    def run_purge(self, *, now: Optional[datetime] = None) -> list[str]:
        return self.store.purge_due_atoms(now=now)

    @staticmethod
    def _actor(actor: Optional[str], reviewer: Optional[str] = None) -> str:
        value = str(actor or reviewer or "").strip()
        if not value:
            raise ValueError("actor is required")
        return value

    @staticmethod
    def _optional_actor(actor: Optional[str]) -> Optional[str]:
        value = str(actor or "").strip()
        return value or None

    @staticmethod
    def _candidate_json(candidate: CandidateAtom | None) -> str | None:
        if candidate is None:
            return None
        return json.dumps(
            {
                "candidate_id": candidate.candidate_id,
                "atom_type": candidate.atom_type.value,
                "canonical_text": candidate.canonical_text,
                "source_refs": [contract_to_dict(ref) for ref in candidate.source_refs],
                "entities": candidate.entities,
                "topics": candidate.topics,
                "confidence": candidate.confidence,
                "salience": candidate.salience,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _candidate_from_json(payload: str | None) -> CandidateAtom | None:
        if not payload:
            return None
        data = json.loads(payload)
        return CandidateAtom(
            candidate_id=str(data["candidate_id"]),
            atom_type=AtomType(str(data["atom_type"])),
            canonical_text=str(data["canonical_text"]),
            source_refs=[source_ref_from_dict(item) for item in data["source_refs"]],
            entities=[str(item) for item in data.get("entities") or []],
            topics=[str(item) for item in data.get("topics") or []],
            confidence=float(data["confidence"]),
            salience=float(data["salience"]),
        )

    def _to_sqlite(self, proposal: MutationProposal) -> dict[str, object]:
        return {
            "proposal_id": proposal.proposal_id,
            "action": proposal.action.value,
            "target_atom_id": proposal.target_atom_id,
            "reason_code": proposal.reason_code,
            "created_at": proposal.created_at.isoformat(),
            "status": proposal.status.value,
            "replacement_candidate_json": self._candidate_json(proposal.replacement_candidate),
            "retention_days": proposal.retention_days,
            "metadata_json": json.dumps(proposal.metadata, ensure_ascii=False),
            "created_by": proposal.created_by,
        }

    def _from_sqlite(self, row: dict[str, object]) -> MutationProposal:
        return MutationProposal(
            proposal_id=str(row["proposal_id"]),
            action=WriteAction(str(row["action"])),
            target_atom_id=str(row["target_atom_id"]),
            reason_code=str(row["reason_code"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            status=ProposalStatus(str(row["status"])),
            replacement_candidate=self._candidate_from_json(row.get("replacement_candidate_json") if isinstance(row, dict) else None),
            retention_days=int(row["retention_days"]),
            metadata={str(key): str(value) for key, value in json.loads(str(row["metadata_json"])).items()},
            reviewer=str(row["reviewer"]) if row.get("reviewer") else None,
            reviewed_at=datetime.fromisoformat(str(row["reviewed_at"])) if row.get("reviewed_at") else None,
            created_by=str(row["created_by"]) if row.get("created_by") else None,
            applied_atom_id=str(row["applied_atom_id"]) if row.get("applied_atom_id") else None,
            apply_identity=str(row["apply_identity"]) if row.get("apply_identity") else None,
            applied_at=datetime.fromisoformat(str(row["applied_at"])) if row.get("applied_at") else None,
            refresh_pending=bool(row.get("refresh_pending")),
        )
