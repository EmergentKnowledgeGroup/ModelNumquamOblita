from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def iter_json_array_objects(path: str | Path, *, chunk_size: int = 1_048_576) -> Iterator[dict[str, Any]]:
    """Stream dict objects from a top-level JSON array without loading whole file."""

    p = Path(path)
    decoder = json.JSONDecoder()
    buf = ""
    started = False

    with p.open("r", encoding="utf-8", errors="replace") as fp:
        eof = False
        index = 0
        while True:
            # Keep only unread suffix before reading next chunk.
            if index > 0:
                buf = buf[index:]
                index = 0

            if not eof:
                chunk = fp.read(chunk_size)
                if chunk:
                    buf += chunk
                else:
                    eof = True

            if not buf:
                break

            need_more = False
            while True:
                while index < len(buf) and buf[index].isspace():
                    index += 1

                if index >= len(buf):
                    break

                if not started:
                    if buf[index] != "[":
                        raise ValueError("JSON root must be an array")
                    started = True
                    index += 1
                    continue

                if buf[index] == ",":
                    index += 1
                    continue

                if buf[index] == "]":
                    return

                try:
                    obj, next_index = decoder.raw_decode(buf, index)
                except json.JSONDecodeError:
                    need_more = True
                    break

                index = next_index
                if isinstance(obj, dict):
                    yield obj

            if eof and need_more:
                raise ValueError("Invalid JSON array payload")
