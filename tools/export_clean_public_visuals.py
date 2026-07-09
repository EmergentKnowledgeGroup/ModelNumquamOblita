#!/usr/bin/env python3
"""Generate simplified public-facing MNO diagrams as SVG and PNG.

These are intentionally not literal draw.io exports. They are clean public
readability diagrams derived from the canonical visual specs: fewer lines,
bundled fan-ins, explicit stages, and no connector paths through boxes.
"""

from __future__ import annotations

import argparse
import html
import math
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "visuals" / "exports" / "clean"
FONT_FAMILY = "Segoe UI, Inter, Arial, sans-serif"

COLORS = {
    "input": ("#fff2cc", "#d6b656"),
    "build": ("#fde9d9", "#c97b63"),
    "review": ("#d5e8d4", "#82b366"),
    "runtime": ("#dae8fc", "#6c8ebf"),
    "govern": ("#f8cecc", "#b85450"),
    "integration": ("#eadcf8", "#9673b9"),
    "helper": ("#fce5f1", "#b8549e"),
    "lane_input": ("#fbf7f1", "#d9b37a"),
    "lane_review": ("#f2f8ef", "#8eb184"),
    "lane_runtime": ("#eef6fd", "#86a8cf"),
    "lane_integration": ("#f5effb", "#b39ad0"),
}


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    kind: str = "runtime"


@dataclass(frozen=True)
class Lane:
    label: str
    x: float
    y: float
    w: float
    h: float
    kind: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    color: str = "#6c8ebf"
    label: str = ""
    source_side: str = "right"
    target_side: str = "left"


@dataclass(frozen=True)
class Diagram:
    slug: str
    title: str
    width: int
    height: int
    lanes: list[Lane]
    nodes: list[Node]
    edges: list[Edge]
    notes: list[Node]


def font_paths() -> tuple[Path | None, Path | None]:
    regulars = [
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bolds = [
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    regular = next((p for p in regulars if p.exists()), None)
    bold = next((p for p in bolds if p.exists()), regular)
    return regular, bold


def load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    regular, bold_path = font_paths()
    target = bold_path if bold else regular
    if target:
        return ImageFont.truetype(str(target), size=size)
    return ImageFont.load_default()


def measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    if not text:
        return 0.0
    box = draw.textbbox((0, 0), text, font=font)
    return float(box[2] - box[0])


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: float) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if measure(draw, candidate, font) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def fit_text(text: str, width: float, height: float, preferred: int) -> tuple[int, list[str], float]:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))
    for size in range(preferred, 9, -1):
        font = load_font(size)
        lines = wrap(probe, text, font, width - 32)
        line_height = size * 1.24
        if len(lines) * line_height <= height - 24:
            return size, lines, line_height
    font = load_font(10)
    lines = wrap(probe, text, font, width - 32)
    return 10, lines, 12.2


def node_color(kind: str) -> tuple[str, str]:
    return COLORS.get(kind, COLORS["runtime"])


def port(node: Node, side: str) -> tuple[float, float]:
    if side == "left":
        return node.x, node.y + node.h / 2
    if side == "right":
        return node.x + node.w, node.y + node.h / 2
    if side == "top":
        return node.x + node.w / 2, node.y
    return node.x + node.w / 2, node.y + node.h


def orthogonal_path(a: Node, b: Node, edge: Edge) -> list[tuple[float, float]]:
    start = port(a, edge.source_side)
    end = port(b, edge.target_side)
    sx, sy = start
    ex, ey = end
    if edge.source_side in {"right", "left"} and edge.target_side in {"right", "left"}:
        mid_x = sx + (ex - sx) / 2
        return [(sx, sy), (mid_x, sy), (mid_x, ey), (ex, ey)]
    if edge.source_side in {"top", "bottom"} and edge.target_side in {"top", "bottom"}:
        mid_y = sy + (ey - sy) / 2
        return [(sx, sy), (sx, mid_y), (ex, mid_y), (ex, ey)]
    return [(sx, sy), (ex, sy), (ex, ey)]


def arrow_points(p1: tuple[float, float], p2: tuple[float, float], size: float = 12.0) -> list[tuple[float, float]]:
    x1, y1 = p1
    x2, y2 = p2
    angle = math.atan2(y2 - y1, x2 - x1)
    left = angle + math.radians(154)
    right = angle - math.radians(154)
    return [
        (x2, y2),
        (x2 + math.cos(left) * size, y2 + math.sin(left) * size),
        (x2 + math.cos(right) * size, y2 + math.sin(right) * size),
    ]


def svg_text(label: str, x: float, y: float, w: float, h: float, *, preferred: int = 18, bold: bool = False) -> str:
    size, lines, line_height = fit_text(label, w, h, preferred)
    total = len(lines) * line_height
    start = y + (h - total) / 2 + size
    weight = "700" if bold else "500"
    tspans = []
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        tspans.append(f'<tspan x="{x + w / 2:.1f}" dy="{dy:.1f}">{html.escape(line)}</tspan>')
    return (
        f'<text x="{x + w / 2:.1f}" y="{start:.1f}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="{size}" font-weight="{weight}" fill="#1f2933">'
        f'{"".join(tspans)}</text>'
    )


def render_svg(diagram: Diagram, path: Path) -> None:
    nodes = {node.id: node for node in diagram.nodes + diagram.notes}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{diagram.width}" height="{diagram.height}" viewBox="0 0 {diagram.width} {diagram.height}" role="img" aria-label="{html.escape(diagram.title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="48" y="56" font-family="{FONT_FAMILY}" font-size="28" font-weight="800" fill="#243b53">{html.escape(diagram.title)}</text>',
    ]
    for lane in diagram.lanes:
        fill, stroke = node_color(lane.kind)
        parts.append(
            f'<rect x="{lane.x}" y="{lane.y}" width="{lane.w}" height="{lane.h}" rx="10" fill="{fill}" fill-opacity="0.58" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{lane.x + 22}" y="{lane.y + 38}" font-family="{FONT_FAMILY}" font-size="21" font-weight="800" fill="#243b53">{html.escape(lane.label)}</text>'
        )
    arrowheads: list[tuple[str, list[tuple[float, float]]]] = []
    for edge in diagram.edges:
        a = nodes[edge.source]
        b = nodes[edge.target]
        pts = orthogonal_path(a, b, edge)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{edge.color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
        arrowheads.append((edge.color, arrow_points(pts[-2], pts[-1])))
    for node in diagram.nodes + diagram.notes:
        fill, stroke = node_color(node.kind)
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(svg_text(node.label, node.x, node.y, node.w, node.h, preferred=18 if node.h >= 86 else 16))
    for color, arrow in arrowheads:
        parts.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in arrow)}" fill="{color}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def render_png(diagram: Diagram, path: Path, *, scale: int = 2) -> None:
    image = Image.new("RGB", (diagram.width * scale, diagram.height * scale), "white")
    draw = ImageDraw.Draw(image)

    def s(v: float) -> int:
        return int(round(v * scale))

    def rect(box: tuple[float, float, float, float], radius: int, fill: str, outline: str, width: int = 2) -> None:
        x, y, w, h = box
        draw.rounded_rectangle([s(x), s(y), s(x + w), s(y + h)], radius=s(radius), fill=fill, outline=outline, width=s(width))

    title_font = load_font(28 * scale, bold=True)
    draw.text((s(48), s(26)), diagram.title, font=title_font, fill="#243b53")

    for lane in diagram.lanes:
        fill, stroke = node_color(lane.kind)
        rect((lane.x, lane.y, lane.w, lane.h), 10, fill, stroke)
        font = load_font(21 * scale, bold=True)
        draw.text((s(lane.x + 22), s(lane.y + 14)), lane.label, font=font, fill="#243b53")

    nodes = {node.id: node for node in diagram.nodes + diagram.notes}
    arrows: list[tuple[str, list[tuple[int, int]]]] = []
    for edge in diagram.edges:
        pts = orthogonal_path(nodes[edge.source], nodes[edge.target], edge)
        draw.line([(s(x), s(y)) for x, y in pts], fill=edge.color, width=s(2.6), joint="curve")
        arrows.append((edge.color, [(s(x), s(y)) for x, y in arrow_points(pts[-2], pts[-1])]))

    for node in diagram.nodes + diagram.notes:
        fill, stroke = node_color(node.kind)
        rect((node.x, node.y, node.w, node.h), 9, fill, stroke)
        size, lines, line_height = fit_text(node.label, node.w, node.h, 18 if node.h >= 86 else 16)
        font = load_font(size * scale)
        total = line_height * len(lines) * scale
        y = s(node.y) + int(((node.h * scale) - total) / 2)
        for line in lines:
            tw = measure(draw, line, font)
            draw.text((s(node.x + node.w / 2) - int(tw / 2), y), line, font=font, fill="#1f2933")
            y += int(line_height * scale)

    for color, arrow in arrows:
        draw.polygon(arrow, fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def diagrams() -> list[Diagram]:
    return [
        launch_pipeline(),
        runtime_integration(),
        current_pipeline(),
        memory_decision(),
    ]


def launch_pipeline() -> Diagram:
    lanes = [
        Lane("Input And Build", 50, 90, 430, 620, "lane_input"),
        Lane("Review And Truth", 560, 90, 430, 620, "lane_review"),
        Lane("Runtime And Use", 1070, 90, 430, 620, "lane_runtime"),
    ]
    nodes = [
        Node("sources", "Raw sources or existing store\nfiles, folders, exports, atoms.sqlite3", 95, 170, 340, 100, "input"),
        Node("import", "Import\nnormalize, sanitize, extract evidence atoms", 95, 330, 340, 100, "build"),
        Node("draft", "Draft episode cards\nrough memory, not trusted yet", 95, 490, 340, 100, "build"),
        Node("agent", "Optional agent curation\ndraft-only cleanup", 605, 170, 340, 100, "helper"),
        Node("review", "Human review\napprove, edit, reject, annotate lineage", 605, 330, 340, 100, "review"),
        Node("reviewed", "Reviewed cards\ntrusted event memory + correction lineage", 605, 490, 340, 100, "review"),
        Node("launch", "Launch runtime\ndesktop, headless, integration-v1, MCP", 1115, 210, 340, 100, "runtime"),
        Node("use", "Runtime memory sources\nreviewed cards + atoms + quote lane; WSS is strict-scope helper state", 1115, 430, 340, 120, "runtime"),
    ]
    edges = [
        Edge("sources", "import", "#d6b656", source_side="bottom", target_side="top"),
        Edge("import", "draft", "#c97b63", source_side="bottom", target_side="top"),
        Edge("draft", "agent", "#c97b63"),
        Edge("agent", "review", "#b8549e", source_side="bottom", target_side="top"),
        Edge("review", "reviewed", "#82b366", source_side="bottom", target_side="top"),
        Edge("reviewed", "launch", "#82b366"),
        Edge("launch", "use", "#6c8ebf", source_side="bottom", target_side="top"),
    ]
    notes = [
        Node("rule", "Key rule\nreviewed cards become trusted runtime memory; helpers and receipts do not replace review", 310, 760, 930, 96, "govern")
    ]
    return Diagram("mno-launch-pipeline-clean", "MNO Launch Pipeline", 1550, 900, lanes, nodes, edges, notes)


def runtime_integration() -> Diagram:
    lanes = [
        Lane("Entry", 50, 90, 350, 620, "lane_input"),
        Lane("Runtime Core", 460, 90, 520, 620, "lane_runtime"),
        Lane("Outputs", 1040, 90, 430, 620, "lane_integration"),
    ]
    nodes = [
        Node("entry", "Desktop / integration-v1 / MCP / adapters", 95, 210, 260, 100, "input"),
        Node("router", "Router + query shaping", 510, 150, 420, 90, "runtime"),
        Node("memory", "Memory candidate pool\nSTM + reviewed cards + atoms + ANN + raw-context receipt lane", 510, 300, 420, 130, "review"),
        Node("evidence", "Context package + verifier\nbounded evidence; WSS scratchpad_ephemeral by strict scope", 510, 500, 420, 120, "runtime"),
        Node("answer", "Answer / abstain / clarify\nwith evidence metadata", 1085, 180, 340, 110, "helper"),
        Node("why", "context.why\nexplain evidence IDs and citations", 1085, 360, 340, 100, "integration"),
        Node("writeback", "Writeback proposal\nhuman/operator resolve stays authoritative", 1085, 540, 340, 110, "govern"),
    ]
    edges = [
        Edge("entry", "router", "#d6b656"),
        Edge("router", "memory", "#6c8ebf", source_side="bottom", target_side="top"),
        Edge("memory", "evidence", "#82b366", source_side="bottom", target_side="top"),
        Edge("evidence", "answer", "#6c8ebf"),
        Edge("evidence", "why", "#9673b9"),
        Edge("evidence", "writeback", "#b85450"),
    ]
    notes = [
        Node("rule", "Integration rule\nintegration-v1 is the public contract; WSS is scoped work continuity, not memory proof or an adapter truth path", 260, 760, 1000, 96, "govern")
    ]
    return Diagram("mno-runtime-integration-clean", "Runtime And Integration Flow", 1520, 900, lanes, nodes, edges, notes)


def current_pipeline() -> Diagram:
    lanes = [
        Lane("Source Intake", 50, 90, 360, 700, "lane_input"),
        Lane("Truth Build", 470, 90, 360, 700, "lane_review"),
        Lane("Runtime", 890, 90, 360, 700, "lane_runtime"),
        Lane("Integration", 1310, 90, 360, 700, "lane_integration"),
    ]
    nodes = [
        Node("source", "Files / folders / conversation exports / existing store", 90, 180, 280, 100, "input"),
        Node("atoms", "Atom store\nsmall evidence pieces with provenance", 90, 360, 280, 110, "build"),
        Node("raw", "Raw-context receipt lane\noriginal wording support, not truth authority", 90, 550, 280, 120, "build"),
        Node("drafts", "Draft episode cards\nagent curation stays draft-only", 510, 180, 280, 110, "helper"),
        Node("reviewed", "Human-reviewed cards\ncurrent/superseded lineage", 510, 390, 280, 120, "review"),
        Node("retrieval", "Runtime retrieval\nreviewed cards + atoms + helper layers", 930, 210, 280, 120, "runtime"),
        Node("verifier", "Context package + verifier\nstrict-scope WSS; answer, abstain, or clarify", 930, 450, 280, 120, "runtime"),
        Node("api", "integration-v1 / MCP / desktop\nbounded package + writeback proposals", 1350, 300, 280, 150, "integration"),
    ]
    edges = [
        Edge("source", "atoms", "#d6b656", source_side="bottom", target_side="top"),
        Edge("atoms", "raw", "#c97b63", source_side="bottom", target_side="top"),
        Edge("atoms", "drafts", "#c97b63"),
        Edge("drafts", "reviewed", "#b8549e", source_side="bottom", target_side="top"),
        Edge("reviewed", "retrieval", "#82b366"),
        Edge("raw", "retrieval", "#c97b63"),
        Edge("retrieval", "verifier", "#6c8ebf", source_side="bottom", target_side="top"),
        Edge("verifier", "api", "#9673b9"),
    ]
    notes = [
        Node("rule", "Truth boundary\ndrafts, helper memory, scratchpad_ephemeral WSS, and raw wording receipts do not become trusted truth", 390, 840, 950, 100, "govern")
    ]
    return Diagram("mno-current-pipeline-clean", "Current Pipeline, Clean View", 1720, 980, lanes, nodes, edges, notes)


def memory_decision() -> Diagram:
    lanes: list[Lane] = []
    nodes = [
        Node("turn", "Incoming turn", 60, 180, 220, 90, "input"),
        Node("route", "Route + query shape", 350, 180, 250, 90, "runtime"),
        Node("retrieve", "Retrieve candidates\nSTM, reviewed cards, atoms, ANN helper, raw context if asked", 680, 150, 330, 130, "review"),
        Node("fusion", "Fusion + guarded shortlist\nrank, dedupe, support checks", 1090, 160, 320, 110, "runtime"),
        Node("pack", "Context package\nbounded evidence; WSS scratchpad_ephemeral by strict scope", 1090, 380, 320, 100, "runtime"),
        Node("verify", "Verifier\nPASS / ABSTAIN / CLARIFY", 680, 390, 330, 100, "runtime"),
        Node("output", "Final output\nanswer text + evidence metadata", 350, 390, 250, 100, "helper"),
        Node("proposal", "Risky new memory\nproposal-only writeback", 680, 610, 330, 100, "govern"),
    ]
    edges = [
        Edge("turn", "route", "#d6b656"),
        Edge("route", "retrieve", "#6c8ebf"),
        Edge("retrieve", "fusion", "#82b366"),
        Edge("fusion", "pack", "#6c8ebf", source_side="bottom", target_side="top"),
        Edge("pack", "verify", "#6c8ebf", source_side="left", target_side="right"),
        Edge("verify", "output", "#6c8ebf", source_side="left", target_side="right"),
        Edge("verify", "proposal", "#b85450", source_side="bottom", target_side="top"),
    ]
    notes = [
        Node("rule", "Decision rule\nretrieval success is not truth authority; WSS helps work continuity, not memory proof", 310, 780, 860, 92, "govern")
    ]
    return Diagram("mno-runtime-memory-decision-clean", "Runtime Memory And Decision Flow", 1480, 920, lanes, nodes, edges, notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for diagram in diagrams():
        svg = out_dir / f"{diagram.slug}.svg"
        png = out_dir / f"{diagram.slug}.png"
        render_svg(diagram, svg)
        render_png(diagram, png)
        print(f"exported {svg.relative_to(REPO_ROOT)}")
        print(f"exported {png.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
