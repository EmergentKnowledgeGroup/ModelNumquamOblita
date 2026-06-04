from __future__ import annotations

import sqlite3
from pathlib import Path

from engine.retrieval.ann_sidecar import AnnSidecar, AnnSidecarDocument


def _documents() -> list[AnnSidecarDocument]:
    return [
        AnnSidecarDocument(
            atom_id="atom_assistant",
            canonical_text="Cold. Drifting from the assistant axis correlates with harmful outputs.",
        ),
        AnnSidecarDocument(
            atom_id="atom_quote",
            canonical_text="The exact wording about the assistant axis showed up in the previous conversation.",
        ),
        AnnSidecarDocument(
            atom_id="atom_unrelated",
            canonical_text="Fresh basil and mint can brighten a summer cocktail.",
        ),
    ]


def test_ann_sidecar_query_returns_bounded_scope_filtered_ids(tmp_path: Path) -> None:
    sidecar = AnnSidecar(tmp_path / "atoms.ann.sqlite3")
    sidecar.rebuild(documents=_documents(), store_fingerprint="fp_live")

    result = sidecar.query(
        query_text="what exactly did the assistant say about the assistant axis and harmful outputs",
        scope_ids={"atom_assistant", "atom_quote"},
        store_fingerprint="fp_live",
        limit=1,
        max_latency_ms=50.0,
    )

    assert result.used is True
    assert result.fallback_reason == ""
    assert len(result.candidate_ids) == 1
    assert result.candidate_ids[0] in {"atom_assistant", "atom_quote"}


def test_ann_sidecar_query_rejects_fingerprint_mismatch(tmp_path: Path) -> None:
    sidecar = AnnSidecar(tmp_path / "atoms.ann.sqlite3")
    sidecar.rebuild(documents=_documents(), store_fingerprint="fp_old")

    result = sidecar.query(
        query_text="assistant axis harmful outputs",
        scope_ids={"atom_assistant", "atom_quote", "atom_unrelated"},
        store_fingerprint="fp_live",
        limit=3,
        max_latency_ms=50.0,
    )

    assert result.used is False
    assert result.candidate_ids == []
    assert result.fallback_reason == "fingerprint_mismatch"


def test_ann_sidecar_query_ignores_candidates_outside_current_scope(tmp_path: Path) -> None:
    sidecar = AnnSidecar(tmp_path / "atoms.ann.sqlite3")
    sidecar.rebuild(documents=_documents(), store_fingerprint="fp_live")

    result = sidecar.query(
        query_text="assistant axis harmful outputs",
        scope_ids={"atom_quote"},
        store_fingerprint="fp_live",
        limit=4,
        max_latency_ms=50.0,
    )

    assert result.used is True
    assert result.candidate_ids == ["atom_quote"]


def test_ann_sidecar_query_falls_back_when_metadata_is_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "atoms.ann.sqlite3"
    sidecar = AnnSidecar(path)
    sidecar.rebuild(documents=_documents(), store_fingerprint="fp_live")

    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM metadata WHERE key = 'backend_version'")
        conn.commit()

    result = sidecar.query(
        query_text="assistant axis harmful outputs",
        scope_ids={"atom_assistant", "atom_quote", "atom_unrelated"},
        store_fingerprint="fp_live",
        limit=4,
        max_latency_ms=50.0,
    )

    assert result.used is False
    assert result.candidate_ids == []
    assert result.fallback_reason == "incomplete_metadata"
