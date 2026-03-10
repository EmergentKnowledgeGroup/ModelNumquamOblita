from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp

from ..config import DecayPolicy
from ..contracts import AtomType, CandidateAtom, SourceRef
from ..memory import AtomStatus, AtomStore, MemoryAtom
from .builder import ContinuityBuilder
from .model import ContinuitySnapshot, SharedLanguageKey
from .store import ContinuityStore

_LN2 = 0.6931471805599453


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(slots=True)
class ConsolidationSummary:
    """Output metrics from one consolidation pass."""

    decayed_atoms: int
    archived_atoms: int
    promoted_candidates: list[CandidateAtom]
    applied_promotions: int = 0
    snapshot_revision: int | None = None
    snapshot_stats: dict[str, int] = field(default_factory=dict)


class Consolidator:
    """Periodic maintenance pass for salience decay and semantic promotion."""

    def __init__(self, store: AtomStore, *, policy: DecayPolicy) -> None:
        self.store = store
        self.policy = policy

    def run(
        self,
        *,
        now: datetime | None = None,
        apply_promotions: bool = False,
    ) -> ConsolidationSummary:
        as_of = now or datetime.now(timezone.utc)
        decayed = 0
        archived = 0
        for atom in self.store.list_atoms():
            if atom.status in {AtomStatus.TOMBSTONED, AtomStatus.ARCHIVED}:
                continue
            if atom.updated_at == as_of:
                continue
            recognition_bias = 0.0
            bias_reader = getattr(self.store, "recognition_bias", None)
            if callable(bias_reader):
                recognition_bias = float(bias_reader(atom.atom_id))
            new_salience = self._decayed_salience(atom, as_of, recognition_bias=recognition_bias)
            if new_salience < atom.salience:
                atom.salience = new_salience
                atom.updated_at = as_of
                decayed += 1
            if atom.salience <= self.policy.minimum_salience and atom.support_count <= 1:
                atom.status = AtomStatus.ARCHIVED
                atom.updated_at = as_of
                archived += 1

        promoted = self._promote_semantic_candidates(as_of)
        applied = 0
        if apply_promotions:
            for candidate in promoted:
                self.store.add_candidate(candidate, reason="consolidator_promote")
                applied += 1
        return ConsolidationSummary(
            decayed_atoms=decayed,
            archived_atoms=archived,
            promoted_candidates=promoted,
            applied_promotions=applied,
        )

    def rebuild_snapshot(
        self,
        continuity_store: ContinuityStore,
        *,
        builder: ContinuityBuilder | None = None,
        now: datetime | None = None,
        shared_language_keys: list[SharedLanguageKey] | None = None,
    ) -> tuple[int, ContinuitySnapshot]:
        as_of = now or datetime.now(timezone.utc)
        active_builder = builder or ContinuityBuilder()
        snapshot = active_builder.build(
            self.store.list_atoms(),
            now=as_of,
            shared_language_keys=shared_language_keys,
        )
        revision = continuity_store.set_snapshot(snapshot)
        return revision, snapshot

    def run_with_snapshot(
        self,
        continuity_store: ContinuityStore,
        *,
        builder: ContinuityBuilder | None = None,
        now: datetime | None = None,
        shared_language_keys: list[SharedLanguageKey] | None = None,
        apply_promotions: bool = False,
    ) -> ConsolidationSummary:
        as_of = now or datetime.now(timezone.utc)
        summary = self.run(now=as_of, apply_promotions=apply_promotions)
        revision, snapshot = self.rebuild_snapshot(
            continuity_store,
            builder=builder,
            now=as_of,
            shared_language_keys=shared_language_keys,
        )
        summary.snapshot_revision = revision
        summary.snapshot_stats = {
            "constellations": len(snapshot.constellations),
            "narrative_arcs": len(snapshot.narrative_arcs),
            "dynamic_patterns": len(snapshot.dynamic_patterns),
            "shared_language_keys": len(snapshot.shared_language_keys),
        }
        return summary

    def _decayed_salience(
        self,
        atom: MemoryAtom,
        now: datetime,
        *,
        recognition_bias: float = 0.0,
    ) -> float:
        anchor = atom.last_reinforced_at or atom.updated_at
        age_days = max((now - anchor).total_seconds() / 86400.0, 0.0)
        half_life = max(self.policy.half_life_days, 1)
        if recognition_bias > 0:
            half_life *= 1.0 + min(recognition_bias, 1.0) * 0.60
        elif recognition_bias < 0:
            half_life *= max(0.35, 1.0 - min(abs(recognition_bias), 1.0) * 0.55)
        factor = exp((-_LN2 * age_days) / half_life)
        return _clamp01(atom.salience * factor)

    def _promote_semantic_candidates(self, now: datetime) -> list[CandidateAtom]:
        promoted: list[CandidateAtom] = []
        for atom in self.store.list_atoms():
            if atom.status is not AtomStatus.ACTIVE:
                continue
            if atom.atom_type is not AtomType.EPISODE:
                continue
            effective_support = max(atom.support_count, len(atom.source_refs))
            if effective_support < 3:
                continue
            candidate = CandidateAtom(
                candidate_id=f"promo_{atom.atom_id}",
                atom_type=AtomType.ATOMIC_FACT,
                canonical_text=atom.canonical_text,
                source_refs=[
                    SourceRef(source_id=ref.source_id, message_id=ref.message_id, timestamp=now)
                    for ref in atom.source_refs[:3]
                ],
                entities=list(atom.entities),
                topics=list(atom.topics),
                confidence=_clamp01(max(atom.confidence, 0.75)),
                salience=_clamp01(max(atom.salience, 0.60)),
            )
            promoted.append(candidate)
        return promoted
