from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.ingest.streaming_json import iter_json_array_objects


def test_iter_json_array_objects_streams_dicts(tmp_path: Path) -> None:
    payload = [
        {"id": "a", "value": 1},
        {"id": "b", "value": 2},
        "ignored-non-dict",
        {"id": "c", "value": 3},
    ]
    path = tmp_path / "export.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    rows = list(iter_json_array_objects(path, chunk_size=16))
    assert [row["id"] for row in rows] == ["a", "b", "c"]


def test_iter_json_array_objects_requires_array_root(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{\"id\":\"x\"}', encoding="utf-8")

    with pytest.raises(ValueError, match="array"):
        list(iter_json_array_objects(path))
