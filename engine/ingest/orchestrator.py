from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import NumquamOblitaConfig, default_config
from ..memory import MutationReviewQueue, SqliteAtomStore
from ..memory.content_safety import SecretDetectedError, assert_safe_content
from ..write_gate import (
    DeterministicJudgmentAdapter,
    StageAWriteGate,
    StageBContext,
    StageBWriteGate,
    candidate_signature,
    extract_salience_features,
    signature_from_fields,
    source_ref_signature,
)
from ..contracts import CandidateAtom, WriteAction
from .extractor import DeterministicCandidateExtractor
from .parser import ConversationIngestor


@dataclass(slots=True)
class ImportCounters:
    conversations_seen: int = 0
    messages_seen: int = 0
    turns_emitted: int = 0
    candidates_extracted: int = 0
    persisted_add_or_update: int = 0
    proposals_created: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    stage_a_reasons: dict[str, int] = field(default_factory=dict)
    stage_b_reasons: dict[str, int] = field(default_factory=dict)
    rejected_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ImportReport:
    input_path: str
    run_id: str
    started_at: str
    finished_at: str
    ok: bool
    counters: ImportCounters
    store_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "store_path": self.store_path,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "counters": {
                "conversations_seen": self.counters.conversations_seen,
                "messages_seen": self.counters.messages_seen,
                "turns_emitted": self.counters.turns_emitted,
                "candidates_extracted": self.counters.candidates_extracted,
                "persisted_add_or_update": self.counters.persisted_add_or_update,
                "proposals_created": self.counters.proposals_created,
                "skipped_reasons": dict(self.counters.skipped_reasons),
                "stage_a_reasons": dict(self.counters.stage_a_reasons),
                "stage_b_reasons": dict(self.counters.stage_b_reasons),
                "rejected_reasons": dict(self.counters.rejected_reasons),
            },
        }


class ImportOrchestrator:
    """Deterministic import pipeline: parse -> extract -> gate -> persist/propose."""

    def __init__(
        self,
        *,
        ingestor: ConversationIngestor | None = None,
        extractor: DeterministicCandidateExtractor | None = None,
        stage_a: StageAWriteGate | None = None,
        stage_b: StageBWriteGate | None = None,
        config: NumquamOblitaConfig | None = None,
    ) -> None:
        self.ingestor = ingestor or ConversationIngestor()
        self.extractor = extractor or DeterministicCandidateExtractor()
        self.stage_a = stage_a or StageAWriteGate()
        self.stage_b = stage_b or StageBWriteGate(adapter=DeterministicJudgmentAdapter())
        self.config = config or default_config()

    def run(self, *, input_path: str | Path, store: SqliteAtomStore, review_queue: MutationReviewQueue) -> ImportReport:
        started = datetime.now(timezone.utc)
        counters = ImportCounters()
        refs_index, atom_index = self._seed_indexes(store)

        try:
            with store.write_batch():
                for conversation in self.ingestor.iter_export_conversations(input_path):
                    # Reject unsafe source material before normalization, hashing,
                    # raw-context recording, candidate extraction, or any other
                    # durable write.
                    assert_safe_content(conversation)
                    counters.conversations_seen += 1
                    for maybe_turn, maybe_reason in self.ingestor.iter_turns_from_conversation(conversation):
                        counters.messages_seen += 1
                        if maybe_turn is None:
                            self._inc(counters.skipped_reasons, maybe_reason or "unknown")
                            continue
                        counters.turns_emitted += 1

                        if bool(self.config.retrieval.raw_context_sidecar.write_enabled):
                            store.record_raw_turn(maybe_turn)

                        candidates = self.extractor.extract_turn(maybe_turn)
                        if not candidates:
                            for reason, value in self.extractor.stats.skip_reasons.items():
                                if value:
                                    self._inc(counters.skipped_reasons, reason)
                            self.extractor.stats.skip_reasons.clear()
                            continue

                        for candidate in candidates:
                            counters.candidates_extracted += 1
                            signature = candidate_signature(candidate)
                            decision_a = self.stage_a.evaluate(candidate, known_signature_index=refs_index)
                            self._inc(counters.stage_a_reasons, decision_a.reason_code)
                            if decision_a.action is WriteAction.IGNORE:
                                self._inc(counters.rejected_reasons, decision_a.reason_code)
                                continue

                            stage_b_context = self._stage_b_context(candidate, signature, atom_index)
                            decision_b = self.stage_b.evaluate(candidate, context=stage_b_context)
                            self._inc(counters.stage_b_reasons, decision_b.reason_code)

                            if decision_b.action in {WriteAction.ADD, WriteAction.UPDATE}:
                                atom = store.add_candidate(candidate, reason=f"import:{decision_b.reason_code}")
                                counters.persisted_add_or_update += 1
                                refs_index.setdefault(signature, set()).update(
                                    {source_ref_signature(ref) for ref in candidate.source_refs}
                                )
                                atom_index[signature] = atom.atom_id
                                continue

                            if decision_b.action is WriteAction.PROPOSE_EDIT and stage_b_context.existing_atom_id:
                                review_queue.propose_edit(
                                    target_atom_id=stage_b_context.existing_atom_id,
                                    replacement_candidate=candidate,
                                    reason_code=decision_b.reason_code,
                                )
                                counters.proposals_created += 1
                                continue

                            if decision_b.action is WriteAction.PROPOSE_DELETE and stage_b_context.existing_atom_id:
                                review_queue.propose_delete(
                                    target_atom_id=stage_b_context.existing_atom_id,
                                    reason_code=decision_b.reason_code,
                                )
                                counters.proposals_created += 1
                                continue

                            self._inc(counters.rejected_reasons, decision_b.reason_code)

            return ImportReport(
                input_path=str(input_path),
                run_id=f"import_{uuid4().hex[:10]}",
                started_at=started.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                ok=True,
                counters=counters,
            )
        except Exception as exc:
            is_content_safety_rejection = isinstance(exc, SecretDetectedError)
            return ImportReport(
                input_path=str(input_path),
                run_id=f"import_{uuid4().hex[:10]}",
                started_at=started.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                ok=False,
                counters=counters,
                error_code="CONTENT_SAFETY_REJECTED" if is_content_safety_rejection else "INGEST_FAILURE",
                error_message=SecretDetectedError.code if is_content_safety_rejection else str(exc),
            )

    def _seed_indexes(self, store: SqliteAtomStore) -> tuple[dict[str, set[str]], dict[str, str]]:
        refs_index: dict[str, set[str]] = {}
        atom_index: dict[str, str] = {}
        for atom in store.list_atoms():
            signature = signature_from_fields(
                atom_type=atom.atom_type.value,
                canonical_text=atom.canonical_text,
                entities=atom.entities,
                topics=atom.topics,
            )
            refs_index.setdefault(signature, set()).update(source_ref_signature(ref) for ref in atom.source_refs)
            atom_index[signature] = atom.atom_id
        return refs_index, atom_index

    def _stage_b_context(self, candidate: CandidateAtom, signature: str, atom_index: dict[str, str]) -> StageBContext:
        features = extract_salience_features(candidate)
        return StageBContext(
            existing_atom_id=atom_index.get(signature),
            conflict_risk=0.0,
            recurrence=min(1.0, len(candidate.source_refs) / 3.0),
            novelty=0.2 if signature in atom_index else 0.9,
            identity_relevance=features.identity_relevance,
        )

    @staticmethod
    def _inc(counter: dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1


def run_sqlite_import_job(
    *,
    input_path: str | Path,
    sqlite_path: str | Path,
    orchestrator: ImportOrchestrator | None = None,
    retention_days: int = 30,
    config: NumquamOblitaConfig | None = None,
) -> ImportReport:
    """Run import against a shadow sqlite store then atomically swap on success."""

    target = Path(sqlite_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shadow = target.with_name(f"{target.name}.tmp_{uuid4().hex}")
    if target.exists():
        _backup_sqlite_store(target, shadow)

    store = SqliteAtomStore(shadow)
    queue = MutationReviewQueue(store, default_retention_days=retention_days)
    runner = orchestrator or ImportOrchestrator(config=config)

    try:
        report = runner.run(input_path=input_path, store=store, review_queue=queue)
    finally:
        store.close()

    if report.ok:
        os.replace(shadow, target)
        report.store_path = str(target)
    else:
        try:
            shadow.unlink(missing_ok=True)
        except Exception:
            pass
    return report


def _backup_sqlite_store(source_path: str | Path, target_path: str | Path) -> Path:
    """Create a consistent SQLite snapshot, including committed WAL state."""

    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if source == target:
        raise ValueError("SQLite snapshot target must differ from source")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as source_conn, closing(
            sqlite3.connect(str(target))
        ) as target_conn:
            source_conn.backup(target_conn)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def write_import_report(report: ImportReport, *, json_path: str | Path, md_path: str | Path) -> tuple[Path, Path]:
    out_json = Path(json_path)
    out_md = Path(md_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    payload = report.to_dict()
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Import Report",
        "",
        f"- input: `{report.input_path}`",
        f"- run_id: `{report.run_id}`",
        f"- ok: `{report.ok}`",
        f"- started_at: `{report.started_at}`",
        f"- finished_at: `{report.finished_at}`",
    ]
    if report.store_path:
        lines.append(f"- store_path: `{report.store_path}`")
    if report.error_code:
        lines.append(f"- error_code: `{report.error_code}`")
    if report.error_message:
        lines.append(f"- error_message: `{report.error_message}`")

    counters = report.counters
    lines.extend(
        [
            "",
            "## Counters",
            f"- conversations_seen: {counters.conversations_seen}",
            f"- messages_seen: {counters.messages_seen}",
            f"- turns_emitted: {counters.turns_emitted}",
            f"- candidates_extracted: {counters.candidates_extracted}",
            f"- persisted_add_or_update: {counters.persisted_add_or_update}",
            f"- proposals_created: {counters.proposals_created}",
            "",
            "## Rejection Reasons",
        ]
    )
    if counters.rejected_reasons:
        for key, value in sorted(counters.rejected_reasons.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- (none)")

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_json, out_md
