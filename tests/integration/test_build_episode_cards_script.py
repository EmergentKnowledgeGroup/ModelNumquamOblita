from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import SqliteAtomStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _seed_candidate(
    candidate_id: str,
    text: str,
    *,
    source_id: str,
    message_id: str,
    topic: str,
    ts: str,
) -> CandidateAtom:
    timestamp = datetime.fromisoformat(ts)
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=message_id,
                timestamp=timestamp,
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.9,
        salience=0.75,
    )


def _build_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    try:
        store.add_candidate(
            _seed_candidate(
                "c1",
                "We reviewed the quarterly plan and split it into milestones.",
                source_id="conv_plan",
                message_id="m1",
                topic="planning",
                ts="2026-01-05T10:00:00+00:00",
            )
        )
        store.add_candidate(
            _seed_candidate(
                "c2",
                "You asked for a risk table and I provided three mitigation tracks.",
                source_id="conv_plan",
                message_id="m2",
                topic="planning",
                ts="2026-01-05T10:05:00+00:00",
            )
        )
        store.add_candidate(
            _seed_candidate(
                "c3",
                "Later we switched to tone calibration and style anchors.",
                source_id="conv_style",
                message_id="m9",
                topic="style",
                ts="2026-01-06T14:10:00+00:00",
            )
        )
    finally:
        store.close()


def test_build_episode_cards_script_outputs_event_cards(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_path = tmp_path / "episode_cards.json"
    rejects_path = tmp_path / "episode_cards.rejects.json"
    _build_store(sqlite_path)

    result = subprocess.run(  # noqa: S603 - trusted fixed args in test harness
        [
            sys.executable,
            "tools/build_episode_cards.py",
            "--memories",
            str(sqlite_path),
            "--out",
            str(out_path),
            "--rejects-out",
            str(rejects_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "episode_cards_json=" in result.stdout
    assert "episode_rejects_json=" in result.stdout
    assert out_path.exists()
    assert rejects_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert str(payload.get("schema") or "") == "numquamoblita.episode_cards.v1"
    assert int(payload.get("atom_count") or 0) == 3
    assert int(payload.get("episode_count") or 0) >= 2
    assert int(payload.get("promoted_count") or 0) >= 0
    cards = list(payload.get("cards") or [])
    assert len(cards) >= 2
    assert all(str(item.get("promotion_status") or "") in {"promoted", "candidate"} for item in cards)
    plan_cards = [item for item in cards if str(item.get("source_id")) == "conv_plan"]
    assert plan_cards
    plan_card = max(plan_cards, key=lambda item: int(item.get("atom_count") or 0))
    assert int(plan_card.get("atom_count") or 0) >= 1
    assert int(plan_card.get("citation_count") or 0) >= 1
    assert list(plan_card.get("actors") or [])
    assert list(plan_card.get("topic_tags") or [])
    assert str(plan_card.get("timestamp_start") or "").strip()
    assert str(plan_card.get("timestamp_end") or "").strip()
    assert "quarterly plan" in str(plan_card.get("summary") or "").lower()
    assert str(plan_card.get("title") or "").strip()

    rejects_payload = json.loads(rejects_path.read_text(encoding="utf-8"))
    assert str(rejects_payload.get("schema") or "") == "numquamoblita.episode_cards.rejects.v1"
    assert str(rejects_payload.get("source_cards") or "").strip()
    assert isinstance(rejects_payload.get("rejected"), list)
