from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_episode_card_readout_script(tmp_path: Path) -> None:
    episodes_path = tmp_path / "episode_cards.json"
    out_path = tmp_path / "episode_cards.readout.md"
    episodes_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-02-11T00:00:00+00:00",
                "cards": [
                    {
                        "episode_id": "ep_001",
                        "title": "Roadmap lock-in",
                        "summary": "We decided to lock milestones before adding stretch goals.",
                        "source_id": "conv_plan",
                        "day_key": "2026-01-05",
                        "domain": "planning",
                        "promotion_status": "promoted",
                        "atom_count": 3,
                        "citation_count": 2,
                        "confidence": 0.88,
                        "evidence_strength": 0.81,
                        "retrieval_weight": 0.84,
                        "citations": ["conv_plan#m1", "conv_plan#m2"],
                        "message_ids": ["m1", "m2"],
                        "cue_terms": ["roadmap", "milestones"],
                        "quality_flags": [],
                        "question_seed": "What do you remember about roadmap?",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - trusted fixed args in test harness
        [
            sys.executable,
            "tools/build_episode_card_readout.py",
            "--episodes",
            str(episodes_path),
            "--out",
            str(out_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "episode_readout_md=" in result.stdout
    body = out_path.read_text(encoding="utf-8")
    assert "Episode Card Readout" in body
    assert "Roadmap lock-in" in body
    assert "status: `promoted`" in body
    assert "quality_status: `clean`" in body
    assert "question_seed" in body
