from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_import_memories_script_outputs_reports(tmp_path: Path) -> None:
    export_path = tmp_path / "conversations.json"
    store_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "reports"

    export_path.write_text(
        json.dumps(
            [
                {
                    "conversation_id": "conv-2",
                    "messages": [
                        {
                            "id": "u1",
                            "role": "user",
                            "content": "I remember this workflow and I prefer continuity checks for every run.",
                        },
                        {
                            "id": "a1",
                            "role": "assistant",
                            "content": "We should keep this memory because it helps preserve identity continuity.",
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            "python3",
            "tools/import_memories.py",
            "--input",
            str(export_path),
            "--store",
            str(store_path),
            "--out-dir",
            str(out_dir),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    report_json = [line.split("=", 1)[1] for line in proc.stdout.splitlines() if line.startswith("report_json=")]
    report_md = [line.split("=", 1)[1] for line in proc.stdout.splitlines() if line.startswith("report_md=")]
    assert report_json and Path(report_json[0]).exists()
    assert report_md and Path(report_md[0]).exists()
    assert store_path.exists()
