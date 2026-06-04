#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _clean_text(raw: str) -> str:
    text = str(raw or "")
    text = text.replace("&#10;", " ").replace("&#xa;", " ").replace("<br>", " ")
    return " ".join(text.split())


def audit_file(path: Path, *, long_label_threshold: int) -> dict[str, object]:
    root = ET.parse(path).getroot()
    pages: list[dict[str, object]] = []
    for diagram in root.findall("diagram"):
        model = diagram.find("mxGraphModel")
        graph_root = model.find("root") if model is not None else None
        cells = graph_root.findall("mxCell") if graph_root is not None else []
        vertex_count = 0
        edge_count = 0
        long_labels: list[str] = []
        for cell in cells:
            if cell.get("vertex") == "1":
                vertex_count += 1
                label = _clean_text(cell.get("value") or "")
                if len(label) >= long_label_threshold:
                    long_labels.append(label)
            if cell.get("edge") == "1":
                edge_count += 1
        pages.append(
            {
                "name": str(diagram.get("name") or "").strip(),
                "vertices": vertex_count,
                "edges": edge_count,
                "long_labels": long_labels[:5],
            }
        )
    return {"file": str(path), "pages": pages}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit draw.io XML structure for the MNO visuals.")
    parser.add_argument("paths", nargs="+", help="One or more .drawio files")
    parser.add_argument("--long-label-threshold", type=int, default=90)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    reports = [audit_file(Path(raw).expanduser().resolve(), long_label_threshold=max(1, args.long_label_threshold)) for raw in args.paths]
    if args.json:
        json.dump(reports, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    for report in reports:
        print(f"FILE {report['file']}")
        for page in report["pages"]:
            print(f"  PAGE {page['name']}: vertices={page['vertices']} edges={page['edges']}")
            for label in page["long_labels"]:
                print(f"    long_label: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
