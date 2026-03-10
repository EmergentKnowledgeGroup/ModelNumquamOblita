from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_build_ingest_fixture_script(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([
            {"id": "c1"},
            {"id": "c2"},
            {"id": "c3"},
        ]),
        encoding="utf-8",
    )
    out = tmp_path / "fixture.json"

    subprocess.check_call(
        [
            "python3",
            "tools/build_ingest_fixture.py",
            "--input",
            str(source),
            "--output",
            str(out),
            "--limit",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[2],
    )

    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 2
    assert rows[0]["id"] == "c1"
    assert rows[1]["id"] == "c2"
