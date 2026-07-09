#!/usr/bin/env python3
"""Generate architecture-grade MNO diagrams as SVG and PNG.

These diagrams sit between the simplified public diagrams and the literal
draw.io exports. They preserve internal layers, trust boundaries, runtime
paths, and integration contracts while using buses and explicit lanes to avoid
connector paths through boxes.
"""

from __future__ import annotations

import argparse
import html
import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "visuals" / "exports" / "architecture"
FONT_FAMILY = "Segoe UI, Inter, Arial, sans-serif"

COLORS = {
    "source": ("#fff4db", "#b97818", "#5f3b05"),
    "build": ("#fde8d6", "#b8693d", "#5b2b16"),
    "evidence": ("#e7f3ff", "#4f83bd", "#213f5f"),
    "review": ("#e6f4df", "#5f9d49", "#244c1f"),
    "memory": ("#e1f4f0", "#398f83", "#174a43"),
    "runtime": ("#e8f0ff", "#5f78c8", "#263967"),
    "decision": ("#e9e6ff", "#7869c6", "#312861"),
    "integration": ("#f3e8ff", "#8b5fbf", "#3f285e"),
    "govern": ("#ffe6e3", "#bb5b54", "#612823"),
    "store": ("#edf1f5", "#687989", "#26313b"),
    "bus": ("#f8fafc", "#64748b", "#26313b"),
    "note": ("#fffbe8", "#d6a21f", "#5f4605"),
    "lane_source": ("#fffaf0", "#d9a441", "#5f3b05"),
    "lane_build": ("#fff3eb", "#d18a61", "#5b2b16"),
    "lane_review": ("#f4fbef", "#82b366", "#244c1f"),
    "lane_runtime": ("#f1f6ff", "#7b9bd6", "#263967"),
    "lane_memory": ("#eefaf7", "#65a99d", "#174a43"),
    "lane_integration": ("#faf4ff", "#a889cc", "#3f285e"),
    "lane_govern": ("#fff1ef", "#c8756d", "#612823"),
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
    font_size: int = 18
    bold: bool = False


@dataclass(frozen=True)
class Lane:
    label: str
    x: float
    y: float
    w: float
    h: float
    kind: str
    subtitle: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    color: str = "#5f78c8"
    label: str = ""
    source_side: str = "right"
    target_side: str = "left"
    source_pos: float = 0.5
    target_pos: float = 0.5
    vias: tuple[tuple[float, float], ...] = ()
    dashed: bool = False
    width: float = 2.8
    arrow: bool = True


@dataclass(frozen=True)
class Boundary:
    label: str
    x: float
    y: float
    h: float
    color: str


@dataclass(frozen=True)
class Diagram:
    slug: str
    title: str
    subtitle: str
    width: int
    height: int
    lanes: list[Lane] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    notes: list[Node] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)
    legend: list[tuple[str, str]] = field(default_factory=list)


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


def color(kind: str) -> tuple[str, str, str]:
    return COLORS.get(kind, COLORS["runtime"])


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


def fit_text(text: str, width: float, height: float, preferred: int, *, bold: bool = False) -> tuple[int, list[str], float]:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))
    for size in range(preferred, 9, -1):
        font = load_font(size, bold=bold)
        lines = wrap(probe, text, font, width - 44)
        line_height = size * 1.32
        max_width = max((measure(probe, line, font) for line in lines), default=0)
        if len(lines) * line_height <= height - 36 and max_width <= width - 36:
            return size, lines, line_height
    font = load_font(9, bold=bold)
    return 9, wrap(probe, text, font, width - 44), 12.0


def port(node: Node, side: str, pos: float = 0.5) -> tuple[float, float]:
    pos = max(0.04, min(0.96, pos))
    if side == "left":
        return node.x, node.y + node.h * pos
    if side == "right":
        return node.x + node.w, node.y + node.h * pos
    if side == "top":
        return node.x + node.w * pos, node.y
    return node.x + node.w * pos, node.y + node.h


def edge_points(nodes: dict[str, Node], edge: Edge) -> list[tuple[float, float]]:
    start = port(nodes[edge.source], edge.source_side, edge.source_pos)
    end = port(nodes[edge.target], edge.target_side, edge.target_pos)
    if edge.vias:
        raw = [start, *edge.vias, end]
        points = [raw[0]]
        for nxt in raw[1:]:
            prev = points[-1]
            if abs(prev[0] - nxt[0]) > 1.0 and abs(prev[1] - nxt[1]) > 1.0:
                points.append((nxt[0], prev[1]))
            points.append(nxt)
        return points

    sx, sy = start
    ex, ey = end
    if edge.source_side in {"right", "left"} and edge.target_side in {"right", "left"}:
        if abs(sy - ey) < 1:
            return [start, end]
        mid_x = sx + (ex - sx) / 2
        return [start, (mid_x, sy), (mid_x, ey), end]
    if edge.source_side in {"top", "bottom"} and edge.target_side in {"top", "bottom"}:
        if abs(sx - ex) < 1:
            return [start, end]
        mid_y = sy + (ey - sy) / 2
        return [start, (sx, mid_y), (ex, mid_y), end]
    return [start, (ex, sy), end]


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
    size, lines, line_height = fit_text(label, w, h, preferred, bold=bold)
    total = len(lines) * line_height
    start = y + (h - total) / 2 + size
    weight = "700" if bold else "500"
    text_lines = []
    for index, line in enumerate(lines):
        text_lines.append(
            f'<text x="{x + w / 2:.1f}" y="{start + index * line_height:.1f}" text-anchor="middle" '
            f'font-family="{FONT_FAMILY}" font-size="{size}" font-weight="{weight}" fill="#1f2937">'
            f'{html.escape(line)}</text>'
        )
    return f'<g class="node-label">{"".join(text_lines)}</g>'


def svg_label(text: str, x: float, y: float, *, size: int = 16, weight: int = 700, fill: str = "#334155") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT_FAMILY}" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{html.escape(text)}</text>'
    )


def dash_attr(edge: Edge) -> str:
    return ' stroke-dasharray="8 8"' if edge.dashed else ""


def render_svg(diagram: Diagram, path: Path) -> None:
    nodes = {node.id: node for node in diagram.nodes + diagram.notes}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{diagram.width}" height="{diagram.height}" viewBox="0 0 {diagram.width} {diagram.height}" role="img" aria-label="{html.escape(diagram.title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="52" y="54" font-family="{FONT_FAMILY}" font-size="30" font-weight="800" fill="#1e293b">{html.escape(diagram.title)}</text>',
        f'<text x="52" y="86" font-family="{FONT_FAMILY}" font-size="16" font-weight="500" fill="#64748b">{html.escape(diagram.subtitle)}</text>',
    ]
    for lane in diagram.lanes:
        fill, stroke, text = color(lane.kind)
        parts.append(
            f'<rect x="{lane.x}" y="{lane.y}" width="{lane.w}" height="{lane.h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(svg_label(lane.label, lane.x + 20, lane.y + 34, size=20, weight=800, fill=text))

    for boundary in diagram.boundaries:
        parts.append(
            f'<line x1="{boundary.x:.1f}" y1="{boundary.y:.1f}" x2="{boundary.x:.1f}" y2="{boundary.y + boundary.h:.1f}" '
            f'stroke="{boundary.color}" stroke-width="3" stroke-dasharray="10 8"/>'
        )
        label_y = boundary.y + boundary.h - 8
        parts.append(
            f'<rect x="{boundary.x + 5:.1f}" y="{label_y - 18:.1f}" width="158" height="24" rx="6" fill="#ffffff" fill-opacity="0.92"/>'
        )
        parts.append(
            f'<text x="{boundary.x + 10:.1f}" y="{label_y:.1f}" font-family="{FONT_FAMILY}" '
            f'font-size="14" font-weight="800" fill="{boundary.color}">{html.escape(boundary.label)}</text>'
        )

    arrows: list[tuple[str, list[tuple[float, float]]]] = []
    for edge in diagram.edges:
        pts = edge_points(nodes, edge)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{edge.color}" stroke-width="{edge.width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash_attr(edge)}/>'
        )
        if edge.arrow:
            arrows.append((edge.color, arrow_points(pts[-2], pts[-1])))
        if edge.label:
            lx = (pts[0][0] + pts[-1][0]) / 2
            ly = (pts[0][1] + pts[-1][1]) / 2 - 10
            escaped = html.escape(edge.label)
            parts.append(f'<rect x="{lx - 82:.1f}" y="{ly - 18:.1f}" width="164" height="24" rx="6" fill="#ffffff" fill-opacity="0.92"/>')
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" font-family="{FONT_FAMILY}" '
                f'font-size="13" font-weight="700" fill="#334155">{escaped}</text>'
            )

    for node in diagram.nodes + diagram.notes:
        fill, stroke, _ = color(node.kind)
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(svg_text(node.label, node.x, node.y, node.w, node.h, preferred=node.font_size, bold=node.bold))

    for color_value, arrow in arrows:
        parts.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in arrow)}" fill="{color_value}"/>')

    if diagram.legend:
        lx = 52
        ly = diagram.height - 62
        for kind, label in diagram.legend:
            fill, stroke, text = color(kind)
            parts.append(f'<rect x="{lx:.1f}" y="{ly - 15:.1f}" width="18" height="18" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            parts.append(svg_label(label, lx + 28, ly, size=14, weight=700, fill=text))
            lx += max(160, len(label) * 8 + 52)

    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def render_png(diagram: Diagram, path: Path, *, scale: int = 2) -> None:
    image = Image.new("RGB", (diagram.width * scale, diagram.height * scale), "white")
    draw = ImageDraw.Draw(image)

    def s(v: float) -> int:
        return int(round(v * scale))

    def rect(node: Node | Lane, fill: str, stroke: str, radius: int = 10, width: int = 2) -> None:
        draw.rounded_rectangle(
            [s(node.x), s(node.y), s(node.x + node.w), s(node.y + node.h)],
            radius=s(radius),
            fill=fill,
            outline=stroke,
            width=s(width),
        )

    title_font = load_font(30 * scale, bold=True)
    subtitle_font = load_font(16 * scale)
    draw.text((s(52), s(20)), diagram.title, font=title_font, fill="#1e293b")
    draw.text((s(52), s(66)), diagram.subtitle, font=subtitle_font, fill="#64748b")

    for lane in diagram.lanes:
        fill, stroke, text_color = color(lane.kind)
        rect(lane, fill, stroke, radius=14)
        draw.text((s(lane.x + 20), s(lane.y + 12)), lane.label, font=load_font(20 * scale, bold=True), fill=text_color)

    for boundary in diagram.boundaries:
        y = boundary.y
        while y < boundary.y + boundary.h:
            draw.line([(s(boundary.x), s(y)), (s(boundary.x), s(min(y + 10, boundary.y + boundary.h)))], fill=boundary.color, width=s(3))
            y += 18
        label_y = boundary.y + boundary.h - 8
        draw.rounded_rectangle(
            [s(boundary.x + 5), s(label_y - 18), s(boundary.x + 163), s(label_y + 6)],
            radius=s(6),
            fill="#ffffff",
        )
        draw.text((s(boundary.x + 10), s(label_y - 16)), boundary.label, font=load_font(14 * scale, bold=True), fill=boundary.color)

    nodes = {node.id: node for node in diagram.nodes + diagram.notes}
    arrows: list[tuple[str, list[tuple[int, int]]]] = []
    for edge in diagram.edges:
        pts = edge_points(nodes, edge)
        scaled = [(s(x), s(y)) for x, y in pts]
        if edge.dashed:
            draw_dashed_line(draw, scaled, fill=edge.color, width=max(1, s(edge.width)))
        else:
            draw.line(scaled, fill=edge.color, width=max(1, s(edge.width)), joint="curve")
        if edge.arrow:
            arrows.append((edge.color, [(s(x), s(y)) for x, y in arrow_points(pts[-2], pts[-1])]))
        if edge.label:
            lx = int((scaled[0][0] + scaled[-1][0]) / 2)
            ly = int((scaled[0][1] + scaled[-1][1]) / 2 - 10 * scale)
            draw.rounded_rectangle([lx - s(82), ly - s(18), lx + s(82), ly + s(6)], radius=s(6), fill="#ffffff")
            font = load_font(13 * scale, bold=True)
            tw = measure(draw, edge.label, font)
            draw.text((lx - int(tw / 2), ly - s(14)), edge.label, font=font, fill="#334155")

    for node in diagram.nodes + diagram.notes:
        fill, stroke, _ = color(node.kind)
        rect(node, fill, stroke)
        size, lines, line_height = fit_text(node.label, node.w, node.h, node.font_size, bold=node.bold)
        font = load_font(size * scale, bold=node.bold)
        total = line_height * len(lines) * scale
        y = s(node.y) + int(((node.h * scale) - total) / 2)
        for line in lines:
            tw = measure(draw, line, font)
            draw.text((s(node.x + node.w / 2) - int(tw / 2), y), line, font=font, fill="#1f2937")
            y += int(line_height * scale)

    for color_value, arrow in arrows:
        draw.polygon(arrow, fill=color_value)

    if diagram.legend:
        lx = 52
        ly = diagram.height - 62
        for kind, label in diagram.legend:
            fill, stroke, text_color = color(kind)
            draw.rounded_rectangle([s(lx), s(ly - 15), s(lx + 18), s(ly + 3)], radius=s(4), fill=fill, outline=stroke, width=s(1.5))
            draw.text((s(lx + 28), s(ly - 16)), label, font=load_font(14 * scale, bold=True), fill=text_color)
            lx += max(160, len(label) * 8 + 52)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def draw_dashed_line(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], *, fill: str, width: int, dash: int = 16, gap: int = 12) -> None:
    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        ux = dx / length
        uy = dy / length
        distance = 0.0
        while distance < length:
            seg_start = distance
            seg_end = min(distance + dash, length)
            draw.line(
                [
                    (int(x1 + ux * seg_start), int(y1 + uy * seg_start)),
                    (int(x1 + ux * seg_end), int(y1 + uy * seg_end)),
                ],
                fill=fill,
                width=width,
            )
            distance += dash + gap


def validate_diagram(diagram: Diagram) -> list[str]:
    warnings: list[str] = []
    nodes = {node.id: node for node in diagram.nodes + diagram.notes}
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))
    for node in diagram.nodes + diagram.notes:
        size, lines, line_height = fit_text(node.label, node.w, node.h, node.font_size, bold=node.bold)
        font = load_font(size, bold=node.bold)
        if len(lines) * line_height > node.h - 28:
            warnings.append(f"{diagram.slug}: text too tall in node {node.id}")
        for line in lines:
            if measure(probe, line, font) > node.w - 28:
                warnings.append(f"{diagram.slug}: text too wide in node {node.id}: {line}")
    target_ports: set[tuple[str, int, int]] = set()
    for edge in diagram.edges:
        pts = edge_points(nodes, edge)
        target = pts[-1]
        key = (edge.target, round(target[0]), round(target[1]))
        if edge.arrow and key in target_ports:
            warnings.append(f"{diagram.slug}: duplicate arrow target port {edge.target} at {target}")
        target_ports.add(key)
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) > 1.0 and abs(a[1] - b[1]) > 1.0:
                warnings.append(f"{diagram.slug}: edge {edge.source}->{edge.target} has diagonal segment {a}->{b}")
        for node in diagram.nodes + diagram.notes:
            if node.id in {edge.source, edge.target}:
                continue
            for a, b in zip(pts, pts[1:]):
                if segment_intersects_rect(a, b, node, pad=4):
                    warnings.append(f"{diagram.slug}: edge {edge.source}->{edge.target} crosses node {node.id}")
    return warnings


def segment_intersects_rect(a: tuple[float, float], b: tuple[float, float], node: Node, *, pad: float = 0) -> bool:
    x1, y1 = a
    x2, y2 = b
    left = node.x - pad
    right = node.x + node.w + pad
    top = node.y - pad
    bottom = node.y + node.h + pad
    if abs(y1 - y2) < 0.1:
        y = y1
        if not (top <= y <= bottom):
            return False
        lo, hi = sorted((x1, x2))
        return max(lo, left) < min(hi, right)
    if abs(x1 - x2) < 0.1:
        x = x1
        if not (left <= x <= right):
            return False
        lo, hi = sorted((y1, y2))
        return max(lo, top) < min(hi, bottom)
    return False


def common_legend() -> list[tuple[str, str]]:
    return [
        ("source", "source"),
        ("evidence", "evidence"),
        ("review", "reviewed truth"),
        ("runtime", "runtime"),
        ("integration", "integration"),
        ("govern", "governance"),
    ]


def diagrams() -> list[Diagram]:
    return [
        system_context(),
        build_pipeline(),
        runtime_retrieval(),
        memory_trust_boundaries(),
        integration_contract(),
        data_lineage(),
        deployment_process(),
    ]


def system_context() -> Diagram:
    lanes = [
        Lane("Operator And Sources", 48, 110, 320, 690, "lane_source", "what enters the local workspace"),
        Lane("Build And Review", 425, 110, 355, 690, "lane_review", "where evidence becomes reviewed memory"),
        Lane("Runtime Core", 880, 110, 355, 690, "lane_runtime", "request handling and evidence decisions"),
        Lane("Integration Surfaces", 1390, 110, 360, 690, "lane_integration", "how tools and apps talk to MNO"),
    ]
    nodes = [
        Node("raw_sources", "Raw files, folders, exports\nplus optional existing atom store", 80, 165, 255, 92, "source"),
        Node("setup", "Guided setup workspace\npicker-first staging and launch", 80, 360, 255, 92, "source"),
        Node("operator", "Human reviewer / operator\napproves memory changes", 80, 585, 255, 92, "govern"),
        Node("importer", "Import and normalization\nsanitized turns, roles, timestamps", 465, 165, 270, 92, "build"),
        Node("atoms", "Atom store\ncanonical evidence substrate", 465, 315, 270, 92, "evidence"),
        Node("review_pack", "Review pack and UI\ndraft cards become reviewable", 465, 465, 270, 92, "review"),
        Node("reviewed_cards", "Reviewed episode cards\ntrusted runtime event memory", 465, 615, 270, 92, "review"),
        Node("memory_bus", "memory\ninputs", 800, 330, 68, 330, "bus", 13, True),
        Node("entry_bus", "request\nentry", 1300, 220, 68, 410, "bus", 13, True),
        Node("runtime_session", "RuntimeSession\nrequest entry and orchestration", 930, 170, 255, 92, "runtime"),
        Node("retrieval", "Retrieval engine\nfusion across trusted and helper layers", 930, 345, 255, 110, "runtime"),
        Node("evidence_pack", "Context package\nbounded evidence plus strict active-scope scratchpad_ephemeral WSS", 930, 520, 255, 92, "evidence"),
        Node("verifier", "Verifier and responder\nanswer, abstain, or clarify", 930, 655, 255, 92, "decision"),
        Node("desktop", "Desktop shell\nmanaged local operator surface", 1430, 165, 280, 86, "integration"),
        Node("iv1", "integration-v1\npreferred orchestration contract", 1430, 315, 280, 86, "integration"),
        Node("mcp", "MCP sidecar and adapters\nOpenClaw, Hermes, Nanobot", 1430, 465, 280, 96, "integration"),
        Node("outcomes", "Response metadata\ncontext.why and proposal writeback", 1430, 625, 280, 100, "govern"),
    ]
    edges = [
        Edge("raw_sources", "importer", "#b97818", target_pos=0.35),
        Edge("setup", "importer", "#b97818", source_pos=0.35, target_pos=0.75, vias=((385, 392), (385, 235))),
        Edge("importer", "atoms", "#b8693d", source_side="bottom", target_side="top"),
        Edge("atoms", "review_pack", "#4f83bd", source_side="bottom", target_side="top"),
        Edge("operator", "review_pack", "#bb5b54", source_pos=0.36, target_pos=0.72, vias=((385, 618), (385, 532))),
        Edge("review_pack", "reviewed_cards", "#5f9d49", source_side="bottom", target_side="top"),
        Edge("atoms", "memory_bus", "#4f83bd", target_pos=0.22),
        Edge("reviewed_cards", "memory_bus", "#5f9d49", target_pos=0.78),
        Edge("memory_bus", "retrieval", "#64748b", source_pos=0.46, target_pos=0.5),
        Edge("desktop", "entry_bus", "#8b5fbf", source_side="left", target_side="right", target_pos=0.16),
        Edge("iv1", "entry_bus", "#8b5fbf", source_side="left", target_side="right", target_pos=0.45),
        Edge("mcp", "entry_bus", "#8b5fbf", source_side="left", target_side="right", target_pos=0.72),
        Edge("entry_bus", "runtime_session", "#64748b", source_side="left", target_side="right", source_pos=0.22, target_pos=0.65),
        Edge("runtime_session", "retrieval", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("retrieval", "evidence_pack", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("evidence_pack", "verifier", "#7869c6", source_side="bottom", target_side="top"),
        Edge("verifier", "outcomes", "#bb5b54", target_pos=0.6),
    ]
    notes = [
        Node("truth_rule", "Architectural invariant\nOnly reviewed cards become trusted truth. Atoms and wording receipts support evidence; WSS supports work continuity only.", 380, 845, 1010, 86, "note", 17, True)
    ]
    boundaries = [
        Boundary("truth gate", 398, 130, 640, "#bb5b54"),
        Boundary("public contract", 1372, 130, 640, "#8b5fbf"),
    ]
    return Diagram(
        "mno-architecture-system-context",
        "MNO Architecture - System Context",
        "How local sources, reviewed memory, runtime decisions, and integration surfaces fit together.",
        1800,
        1100,
        lanes,
        nodes,
        edges,
        notes,
        boundaries,
        common_legend(),
    )


def build_pipeline() -> Diagram:
    lanes = [
        Lane("Source Staging", 45, 120, 300, 705, "lane_source", "files and existing stores"),
        Lane("Import And Evidence", 390, 120, 330, 705, "lane_build", "normalized atoms and receipts"),
        Lane("Draft Build", 765, 120, 300, 705, "lane_review", "untrusted memory drafts"),
        Lane("Human Review Gate", 1110, 120, 330, 705, "lane_govern", "approval and lineage"),
        Lane("Runtime Publication", 1485, 120, 330, 705, "lane_runtime", "trusted memory available to runtime"),
    ]
    nodes = [
        Node("raw", "Raw exports and folders\nJSON, JSONL, TXT, MD, mixed archives", 75, 175, 240, 88, "source"),
        Node("existing", "Existing MNO store\nappend or reuse atoms.sqlite3", 75, 345, 240, 88, "store"),
        Node("staging", "Picker-first staging\nsource list, filters, setup workspace", 75, 585, 240, 92, "source"),
        Node("normalizer", "Loader and normalizer\nclean turns, roles, timestamps", 425, 175, 260, 88, "build"),
        Node("atom_writer", "Atom writer\nsmall evidence units with provenance IDs", 425, 345, 260, 92, "evidence"),
        Node("raw_sidecar", "Raw-context sidecar\nread-only wording receipt lane", 425, 585, 260, 92, "evidence"),
        Node("builder", "Episode card builder\ndraft event memory from atoms", 800, 230, 230, 92, "review"),
        Node("assistant", "Optional assistant curation\ndraft-only cleanup and grouping", 800, 445, 230, 100, "integration"),
        Node("review_ui", "Review pack and UI\napprove, edit, reject, annotate", 1145, 230, 260, 96, "govern"),
        Node("lineage", "Truth-lineage finalizer\ntruth_family_id, current flag, supersedes", 1145, 445, 260, 104, "govern"),
        Node("compiled", "Compiled reviewed cards\nepisode_cards.reviewed.json", 1525, 230, 250, 96, "review"),
        Node("runtime", "Runtime memory registry\nreviewed cards + atoms + quote lane\nWSS sidecar stays helper-only", 1525, 445, 250, 104, "runtime"),
        Node("launch", "Launch surfaces\ndesktop, headless HTTP, MCP, integration-v1", 1525, 640, 250, 100, "integration"),
    ]
    edges = [
        Edge("raw", "normalizer", "#b97818", target_pos=0.35),
        Edge("staging", "normalizer", "#b97818", source_pos=0.35, target_pos=0.75, vias=((365, 617), (365, 241))),
        Edge("normalizer", "atom_writer", "#b8693d", source_side="bottom", target_side="top"),
        Edge("existing", "atom_writer", "#687989", source_pos=0.45, target_pos=0.5),
        Edge("atom_writer", "raw_sidecar", "#4f83bd", source_side="bottom", target_side="top", dashed=True, label="wording receipts"),
        Edge("atom_writer", "builder", "#4f83bd", source_pos=0.35, target_pos=0.45),
        Edge("builder", "assistant", "#5f9d49", source_side="bottom", target_side="top", dashed=True),
        Edge("builder", "review_ui", "#5f9d49", source_pos=0.55, target_pos=0.45),
        Edge("assistant", "review_ui", "#8b5fbf", source_pos=0.35, target_pos=0.75, vias=((1087, 495), (1087, 302))),
        Edge("review_ui", "lineage", "#bb5b54", source_side="bottom", target_side="top"),
        Edge("lineage", "compiled", "#5f9d49", source_pos=0.35, target_pos=0.7, vias=((1464, 481), (1464, 297))),
        Edge("compiled", "runtime", "#5f9d49", source_side="bottom", target_side="top"),
        Edge("raw_sidecar", "runtime", "#4f83bd", source_pos=0.55, target_pos=0.8, dashed=True, vias=((740, 636), (740, 765), (1505, 765), (1505, 528))),
        Edge("runtime", "launch", "#5f78c8", source_side="bottom", target_side="top"),
    ]
    notes = [
        Node("draft_rule", "Draft boundary\nAssistant curation can improve drafts, but the review gate is the first authority-producing step.", 785, 860, 690, 82, "note", 17, True)
    ]
    boundaries = [Boundary("untrusted draft zone", 1088, 140, 665, "#bb5b54")]
    return Diagram(
        "mno-architecture-build-pipeline",
        "MNO Architecture - Build Pipeline",
        "From messy local sources to reviewed runtime memory, with draft and truth boundaries visible.",
        1860,
        1100,
        lanes,
        nodes,
        edges,
        notes,
        boundaries,
        common_legend(),
    )


def runtime_retrieval() -> Diagram:
    lanes = [
        Lane("Request", 45, 120, 280, 730, "lane_source", "one live turn"),
        Lane("Retrieval Sources", 375, 120, 360, 730, "lane_memory", "trusted plus helper layers"),
        Lane("Fusion And Ranking", 800, 120, 300, 730, "lane_runtime", "bounded candidate control"),
        Lane("Evidence And Decision", 1165, 120, 330, 730, "lane_runtime", "context package and verifier"),
        Lane("Outcomes", 1560, 120, 300, 730, "lane_integration", "what leaves the runtime"),
    ]
    nodes = [
        Node("turn", "Incoming turn\nuser request plus current context", 80, 210, 210, 90, "source"),
        Node("query", "Router and query shaping\nmode, scope, quote intent", 80, 470, 210, 96, "runtime"),
        Node("source_bus", "candidate\nbus", 732, 185, 86, 520, "bus", 11, True),
        Node("immediate", "Immediate context\ncurrent turn and request-local state", 420, 165, 270, 82, "source"),
        Node("stm", "STM / session state\nshort-term notes and rolling summary", 420, 275, 270, 82, "memory"),
        Node("provisional", "Helper work state\nprovisional memory + strict active-scope WSS", 420, 385, 270, 82, "memory"),
        Node("reviewed", "Reviewed episodes\ntrusted event memory with lineage", 420, 495, 270, 82, "review"),
        Node("atoms_ann", "Atoms + bounded ANN\ncanonical evidence and additive candidates", 420, 605, 270, 92, "evidence"),
        Node("raw_context", "Raw-context sidecar\nexact wording and provenance only when asked", 420, 725, 270, 82, "evidence"),
        Node("retrieval", "Hybrid retrieval\nlexical, BM25, semantic, sequence, graph", 835, 230, 230, 98, "runtime"),
        Node("lineage", "Lineage-aware resolution\nprefer current reviewed truth", 835, 425, 230, 98, "review"),
        Node("shortlist", "Guarded shortlist\nbounded, deduped, evidence-ranked", 835, 620, 230, 98, "runtime"),
        Node("package", "Context package\nevidence plus scratchpad_ephemeral WSS when strict active scope is present", 1205, 250, 250, 98, "evidence"),
        Node("quote", "Quote / provenance expansion\nonly for exact wording asks", 1205, 445, 250, 98, "evidence"),
        Node("verifier", "Verifier and answer path\nPASS, ABSTAIN, or CLARIFY", 1205, 640, 250, 98, "decision"),
        Node("answer", "Final response\nanswer text plus evidence metadata", 1600, 225, 220, 96, "integration"),
        Node("why", "context.why\nIDs, citations, and reason trail", 1600, 430, 220, 96, "integration"),
        Node("proposal", "Proposal-only writeback\nno silent truth mutation", 1600, 635, 220, 96, "govern"),
    ]
    edges = [
        Edge("turn", "query", "#b97818", source_side="bottom", target_side="top"),
        Edge("query", "source_bus", "#5f78c8", target_side="top", target_pos=0.5, vias=((348, 518), (348, 112), (775, 112))),
        Edge("immediate", "source_bus", "#b97818", target_pos=0.14),
        Edge("stm", "source_bus", "#398f83", target_pos=0.28),
        Edge("provisional", "source_bus", "#398f83", target_pos=0.42),
        Edge("reviewed", "source_bus", "#5f9d49", target_pos=0.57),
        Edge("atoms_ann", "source_bus", "#4f83bd", target_pos=0.73),
        Edge("raw_context", "source_bus", "#4f83bd", target_pos=0.9, dashed=True),
        Edge("source_bus", "retrieval", "#64748b", source_pos=0.16, target_pos=0.5),
        Edge("retrieval", "lineage", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("lineage", "shortlist", "#5f9d49", source_side="bottom", target_side="top"),
        Edge("shortlist", "package", "#5f78c8", source_pos=0.42, target_pos=0.72, vias=((1130, 668), (1130, 318))),
        Edge("shortlist", "quote", "#4f83bd", source_pos=0.58, target_pos=0.5, dashed=True),
        Edge("package", "verifier", "#7869c6", source_side="right", target_side="top", target_pos=0.35, vias=((1495, 299), (1495, 610), (1292, 610))),
        Edge("quote", "verifier", "#4f83bd", source_side="bottom", target_side="top", target_pos=0.65, dashed=True),
        Edge("verifier", "answer", "#7869c6", source_pos=0.34, target_pos=0.7, vias=((1525, 673), (1525, 292))),
        Edge("verifier", "why", "#8b5fbf", source_pos=0.5, target_pos=0.5),
        Edge("verifier", "proposal", "#bb5b54", source_pos=0.66, target_pos=0.5),
    ]
    notes = [
        Node("runtime_rule", "Decision rule\nRetrieval success is not authority. WSS can help resume work under strict active scope, but cannot prove memory.", 635, 885, 750, 78, "note", 17, True)
    ]
    return Diagram(
        "mno-architecture-runtime-retrieval",
        "MNO Architecture - Runtime Retrieval",
        "The live request path from route selection through memory fusion, evidence packaging, and governed output.",
        1900,
        1110,
        lanes,
        nodes,
        edges,
        notes,
        [],
        common_legend(),
    )


def memory_trust_boundaries() -> Diagram:
    lanes = [
        Lane("Request-Local", 55, 135, 330, 165, "lane_source", "highest freshness, shortest lifetime"),
        Lane("Helper Memory", 55, 340, 330, 250, "lane_memory", "useful but lower authority"),
        Lane("Canonical Evidence", 55, 630, 330, 165, "lane_build", "durable evidence substrate"),
        Lane("Reviewed Truth", 465, 135, 410, 300, "lane_review", "human-approved event memory"),
        Lane("Governance", 465, 485, 410, 310, "lane_govern", "writeback and correction control"),
        Lane("Runtime Read Path", 995, 135, 520, 660, "lane_runtime", "how layers are consulted safely"),
    ]
    nodes = [
        Node("immediate", "Immediate context\ncurrent turn and request-local state", 95, 185, 250, 74, "source"),
        Node("stm", "STM / session state\nshort-term notes and rolling summary", 95, 385, 250, 78, "memory"),
        Node("provisional", "Helper work state\nprovisional memory + strict active-scope WSS", 95, 485, 250, 78, "memory"),
        Node("atoms", "Canonical atom store\nsmall evidence units with provenance", 95, 675, 250, 78, "evidence"),
        Node("reviewed", "Reviewed episode cards\ntrusted runtime event memory", 505, 185, 300, 82, "review"),
        Node("lineage", "Truth-lineage metadata\ncurrent vs superseded reviewed truth", 505, 310, 300, 82, "review"),
        Node("queue", "Mutation review queue\nproposals wait for operator resolve", 505, 540, 300, 82, "govern"),
        Node("raw_context", "Raw-context receipts\nread-only exact wording support", 505, 665, 300, 82, "evidence"),
        Node("read_bus", "layered\nread bus", 900, 220, 78, 490, "bus", 12, True),
        Node("rank", "Rank and resolve\nreviewed truth outranks helper memory", 1045, 205, 400, 92, "runtime"),
        Node("bound", "Bounded context package\ncitations, IDs, source scope, scratchpad_ephemeral WSS by strict active scope", 1045, 370, 400, 92, "evidence"),
        Node("verify", "Verifier\npasses, abstains, or asks to clarify", 1045, 535, 400, 92, "decision"),
        Node("proposal", "Proposal output path\nnew memory cannot enter truth silently", 1045, 680, 400, 78, "govern"),
    ]
    edges = [
        Edge("immediate", "read_bus", "#b97818", target_pos=0.1, vias=((410, 222), (410, 104), (910, 104))),
        Edge("stm", "read_bus", "#398f83", target_pos=0.27, vias=((420, 424), (420, 118), (910, 118))),
        Edge("provisional", "read_bus", "#398f83", target_pos=0.43, vias=((430, 524), (430, 132), (910, 132))),
        Edge("atoms", "read_bus", "#4f83bd", target_pos=0.75, vias=((430, 714), (430, 820), (910, 820))),
        Edge("reviewed", "read_bus", "#5f9d49", source_pos=0.42, target_pos=0.18),
        Edge("lineage", "read_bus", "#5f9d49", source_pos=0.58, target_pos=0.34),
        Edge("raw_context", "read_bus", "#4f83bd", source_pos=0.4, target_pos=0.92, dashed=True),
        Edge("read_bus", "rank", "#64748b", source_pos=0.16, target_pos=0.45),
        Edge("rank", "bound", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("bound", "verify", "#7869c6", source_side="bottom", target_side="top"),
        Edge("verify", "proposal", "#bb5b54", source_side="bottom", target_side="top"),
        Edge("proposal", "queue", "#bb5b54", source_side="bottom", target_side="right", source_pos=0.15, target_pos=0.62, vias=((1105, 820), (850, 820), (850, 591))),
        Edge("queue", "reviewed", "#bb5b54", source_side="left", target_side="bottom", source_pos=0.35, target_pos=0.5, dashed=True, vias=((435, 569), (435, 300), (655, 300))),
    ]
    notes = [
        Node("trust_note", "Trust ordering\nreviewed truth carries authority; raw receipts support evidence; WSS scratchpad_ephemeral supports work continuity, not proof.", 410, 845, 905, 78, "note", 17, True)
    ]
    boundaries = [Boundary("authority boundary", 430, 150, 640, "#bb5b54"), Boundary("runtime read boundary", 970, 150, 640, "#5f78c8")]
    return Diagram(
        "mno-architecture-memory-trust-boundaries",
        "MNO Architecture - Memory Trust Boundaries",
        "Which memory layers exist, what each layer is allowed to do, and how runtime reads them without collapsing trust levels.",
        1600,
        1090,
        lanes,
        nodes,
        edges,
        notes,
        boundaries,
        common_legend(),
    )


def integration_contract() -> Diagram:
    lanes = [
        Lane("Launchers And Clients", 50, 125, 315, 700, "lane_source", "entry points people and tools use"),
        Lane("Public Contract", 440, 125, 360, 700, "lane_integration", "integration-v1 boundary"),
        Lane("Runtime Session", 875, 125, 360, 700, "lane_runtime", "single request orchestration path"),
        Lane("Compatibility Layer", 1310, 125, 300, 700, "lane_integration", "wrappers around the contract"),
        Lane("Governed Outputs", 1675, 125, 280, 700, "lane_govern", "response and writeback behavior"),
    ]
    nodes = [
        Node("desktop", "Desktop shell\nmanaged local operator surface", 85, 175, 245, 82, "integration"),
        Node("headless", "Headless launcher\nHTTP runtime process", 85, 315, 245, 82, "runtime"),
        Node("setup", "setup_workspace\ninstall, import, launch, bundle export", 85, 455, 245, 92, "source"),
        Node("clients", "Agent or app client\norchestrator hot loop", 85, 605, 245, 82, "source"),
        Node("contract_bus", "integration-v1\ncontract bus", 376, 205, 96, 450, "bus", 10, True),
        Node("turn", "Turn request\ninput, mode, scope, memory policy", 485, 185, 270, 82, "integration"),
        Node("context", "Context package\nbounded evidence plus strict active-scope scratchpad_ephemeral WSS", 485, 315, 270, 82, "evidence"),
        Node("propose", "Memory propose/resolve\nexplicit writeback path", 485, 445, 270, 82, "govern"),
        Node("health", "Health and metadata\ncapabilities, version, diagnostics", 485, 575, 270, 82, "store"),
        Node("session", "RuntimeSession\nmain entry and orchestration", 925, 210, 260, 92, "runtime"),
        Node("retrieval", "Retrieval engine\nmemory fusion and evidence assembly", 925, 375, 260, 96, "runtime"),
        Node("store", "Local stores\natoms, reviewed cards, raw receipts, WSS scratchpad_ephemeral sidecar", 925, 550, 260, 100, "store"),
        Node("mcp", "MCP sidecar\nstdio or HTTP over running runtime", 1350, 225, 220, 88, "integration"),
        Node("adapters", "Compatibility adapters\nOpenClaw, Hermes, Nanobot, generic", 1350, 405, 220, 94, "integration"),
        Node("response", "Answer / abstain / clarify\nsame evidence envelope", 1715, 230, 205, 92, "decision"),
        Node("why", "context.why\ntraceable IDs and citations", 1715, 405, 205, 86, "integration"),
        Node("writeback", "Proposal queue\noperator resolve before truth", 1715, 575, 205, 92, "govern"),
    ]
    edges = [
        Edge("desktop", "contract_bus", "#8b5fbf", target_pos=0.12),
        Edge("headless", "contract_bus", "#5f78c8", target_pos=0.34),
        Edge("setup", "contract_bus", "#b97818", target_pos=0.56),
        Edge("clients", "contract_bus", "#b97818", target_pos=0.78),
        Edge("contract_bus", "turn", "#8b5fbf", source_pos=0.16),
        Edge("contract_bus", "context", "#4f83bd", source_pos=0.39),
        Edge("contract_bus", "propose", "#bb5b54", source_pos=0.61),
        Edge("contract_bus", "health", "#687989", source_pos=0.84),
        Edge("turn", "session", "#8b5fbf", target_pos=0.35),
        Edge("context", "retrieval", "#4f83bd", target_pos=0.45),
        Edge("propose", "store", "#bb5b54", target_pos=0.75),
        Edge("health", "store", "#687989", target_pos=0.35),
        Edge("session", "retrieval", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("retrieval", "store", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("mcp", "session", "#8b5fbf", source_side="left", target_side="right", source_pos=0.35, target_pos=0.4),
        Edge("adapters", "contract_bus", "#8b5fbf", source_side="left", target_side="bottom", source_pos=0.45, target_pos=0.5, dashed=True, vias=((1265, 447), (1265, 765), (424, 765))),
        Edge("session", "response", "#7869c6", source_pos=0.45, target_pos=0.5, vias=((1240, 251), (1240, 106), (1680, 106), (1680, 276))),
        Edge("retrieval", "why", "#8b5fbf", source_pos=0.52, target_pos=0.5, vias=((1240, 425), (1240, 535), (1680, 535), (1680, 448))),
        Edge("store", "writeback", "#bb5b54", source_pos=0.65, target_pos=0.5),
    ]
    notes = [
        Node("contract_rule", "Integration rule\nNew integrations should prefer integration-v1. WSS enters only through strict active-scope context packages, not a truth contract.", 585, 870, 920, 78, "note", 17, True)
    ]
    boundaries = [Boundary("preferred public boundary", 415, 145, 660, "#8b5fbf")]
    return Diagram(
        "mno-architecture-integration-contract",
        "MNO Architecture - Integration Contract",
        "Where desktop, HTTP, MCP, and compatibility adapters attach without becoming separate truth contracts.",
        2000,
        1100,
        lanes,
        nodes,
        edges,
        notes,
        boundaries,
        common_legend(),
    )


def data_lineage() -> Diagram:
    lanes = [
        Lane("Source Identity", 55, 125, 325, 720, "lane_source", "where original material is named"),
        Lane("Evidence IDs", 430, 125, 325, 720, "lane_build", "durable atom and receipt references"),
        Lane("Review IDs", 805, 125, 325, 720, "lane_review", "human decision and lineage metadata"),
        Lane("Runtime Evidence", 1180, 125, 325, 720, "lane_runtime", "read-time selection and citation"),
        Lane("Explainability", 1555, 125, 325, 720, "lane_integration", "what integrators and users can inspect"),
    ]
    nodes = [
        Node("source", "Raw source snapshot\nfile path, export ID, folder batch", 95, 195, 245, 86, "source"),
        Node("turn", "Normalized turn\nrole, timestamp, cleaned text span", 95, 390, 245, 86, "source"),
        Node("receipt", "Original wording receipt\nbounded source-context pointer", 95, 585, 245, 86, "evidence"),
        Node("atom", "Evidence atom\natom_id plus provenance metadata", 470, 245, 245, 86, "evidence"),
        Node("raw_sidecar", "Raw-context sidecar row\nquote lookup key and source span", 470, 540, 245, 92, "evidence"),
        Node("draft", "Draft episode card\ncandidate event memory, not trusted", 845, 210, 245, 88, "memory"),
        Node("decision", "Review decision\napproved, edited, rejected, annotated", 845, 390, 245, 88, "govern"),
        Node("truth_family", "Truth lineage\ntruth_family_id, current flag, supersedes", 845, 575, 245, 96, "review"),
        Node("resolver", "Lineage resolver\ncurrent reviewed truth wins over superseded", 1220, 245, 245, 92, "review"),
        Node("pack", "Evidence pack\natom IDs, card IDs, quote refs", 1220, 440, 245, 92, "evidence"),
        Node("verifier", "Verifier path\nclaim must stay supported by evidence", 1220, 635, 245, 92, "decision"),
        Node("response", "Answer metadata\ncitations and abstain/clarify reason", 1595, 245, 245, 92, "integration"),
        Node("why", "context.why\nreason trail from output back to source", 1595, 440, 245, 92, "integration"),
        Node("audit", "Audit and debug\ntrace cards, atoms, receipts, review choice", 1595, 635, 245, 92, "store"),
    ]
    edges = [
        Edge("source", "turn", "#b97818", source_side="bottom", target_side="top"),
        Edge("turn", "receipt", "#b97818", source_side="bottom", target_side="top", dashed=True),
        Edge("turn", "atom", "#4f83bd", source_pos=0.42, target_pos=0.5),
        Edge("receipt", "raw_sidecar", "#4f83bd", source_pos=0.55, target_pos=0.5, dashed=True),
        Edge("atom", "draft", "#4f83bd", source_pos=0.42, target_pos=0.55),
        Edge("draft", "decision", "#5f9d49", source_side="bottom", target_side="top"),
        Edge("decision", "truth_family", "#bb5b54", source_side="bottom", target_side="top"),
        Edge("truth_family", "resolver", "#5f9d49", source_pos=0.35, target_pos=0.72, vias=((1155, 609), (1155, 309))),
        Edge("raw_sidecar", "pack", "#4f83bd", source_pos=0.5, target_pos=0.7, dashed=True, vias=((780, 586), (780, 805), (1160, 805), (1160, 504))),
        Edge("resolver", "pack", "#5f9d49", source_side="bottom", target_side="top"),
        Edge("pack", "verifier", "#7869c6", source_side="bottom", target_side="top"),
        Edge("verifier", "response", "#7869c6", source_pos=0.35, target_pos=0.7, vias=((1530, 667), (1530, 309))),
        Edge("pack", "why", "#8b5fbf", source_pos=0.5, target_pos=0.5),
        Edge("truth_family", "audit", "#687989", source_pos=0.65, target_pos=0.5, vias=((1155, 637), (1155, 770), (1530, 770), (1530, 681))),
    ]
    notes = [
        Node("lineage_rule", "Lineage rule\nHistory is preserved. Current reviewed cards are preferred at read time, but older reviewed cards remain traceable.", 520, 880, 895, 78, "note", 17, True)
    ]
    boundaries = [Boundary("review creates authority", 780, 145, 675, "#bb5b54")]
    return Diagram(
        "mno-architecture-data-lineage",
        "MNO Architecture - Data Lineage",
        "How source material becomes evidence, reviewed cards, runtime citations, and inspectable context.why trails.",
        1930,
        1110,
        lanes,
        nodes,
        edges,
        notes,
        boundaries,
        common_legend(),
    )


def deployment_process() -> Diagram:
    lanes = [
        Lane("Local Workspace", 55, 125, 345, 715, "lane_source", "files live on the operator machine"),
        Lane("Build Tools", 455, 125, 330, 715, "lane_build", "setup and import commands"),
        Lane("Runtime Processes", 840, 125, 360, 715, "lane_runtime", "desktop, HTTP, and MCP process model"),
        Lane("Integration Clients", 1255, 125, 300, 715, "lane_integration", "agent-facing surfaces"),
        Lane("State And Outputs", 1610, 125, 300, 715, "lane_govern", "what gets written back"),
    ]
    nodes = [
        Node("sources", "Source files and folders\noperator-selected local material", 95, 195, 265, 86, "source"),
        Node("workspace", "runtime/ workspace\nimports, episodes, WSS scratchpad_ephemeral sidecar, logs", 95, 390, 265, 92, "store"),
        Node("review_files", "Review artifacts\nTSV, MD, reviewed JSON", 95, 595, 265, 92, "review"),
        Node("setup", "run_setup_workspace.py\npicker UX, bundle export, launch helpers", 490, 200, 260, 96, "source"),
        Node("import_tools", "Import and build tools\nimport_memories.py, import_ia_db.py, build_episode_cards.py", 490, 400, 260, 112, "build"),
        Node("compile", "Review compile tool\nbuild_episode_review_pack.py --compile-reviewed", 490, 615, 260, 100, "review"),
        Node("desktop", "Electron desktop shell\nmanages local runtime and operator UI", 885, 180, 270, 96, "integration"),
        Node("http_runtime", "Headless HTTP runtime\ntools/run_live_runtime.py", 885, 375, 270, 88, "runtime"),
        Node("mcp_server", "MCP server sidecar\ntools/run_mcp_server.py over runtime", 885, 575, 270, 96, "integration"),
        Node("iv1", "integration-v1 client\npreferred orchestration path", 1295, 220, 220, 90, "integration"),
        Node("adapter", "Compatibility clients\nreference, OpenClaw, Hermes, Nanobot", 1295, 445, 220, 96, "integration"),
        Node("answers", "Responses\nanswer, abstain, clarify, context.why", 1650, 225, 220, 96, "decision"),
        Node("proposals", "Proposal queue\noperator review before truth mutation", 1650, 445, 220, 96, "govern"),
        Node("logs", "Runtime logs and diagnostics\nlocal operational state, not truth", 1650, 650, 220, 86, "store"),
    ]
    edges = [
        Edge("sources", "setup", "#b97818", target_pos=0.35),
        Edge("setup", "workspace", "#b97818", source_side="left", target_side="right", source_pos=0.75, target_pos=0.45, vias=((420, 272), (420, 436))),
        Edge("workspace", "import_tools", "#687989", target_pos=0.5),
        Edge("import_tools", "review_files", "#5f9d49", source_side="left", target_side="right", source_pos=0.75, target_pos=0.45, vias=((420, 484), (420, 636))),
        Edge("review_files", "compile", "#5f9d49"),
        Edge("compile", "http_runtime", "#5f9d49", source_pos=0.35, target_pos=0.7, vias=((815, 650), (815, 437))),
        Edge("setup", "desktop", "#8b5fbf", source_pos=0.35, target_pos=0.5),
        Edge("desktop", "http_runtime", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("http_runtime", "mcp_server", "#5f78c8", source_side="bottom", target_side="top"),
        Edge("http_runtime", "iv1", "#8b5fbf", source_pos=0.35, target_pos=0.65, vias=((1227, 406), (1227, 279))),
        Edge("mcp_server", "adapter", "#8b5fbf", source_pos=0.55, target_pos=0.6),
        Edge("iv1", "answers", "#7869c6", target_pos=0.5),
        Edge("adapter", "answers", "#7869c6", source_pos=0.35, target_pos=0.75, vias=((1580, 479), (1580, 297))),
        Edge("adapter", "proposals", "#bb5b54", source_pos=0.65, target_pos=0.5),
        Edge("http_runtime", "logs", "#687989", source_pos=0.75, target_pos=0.5, vias=((1227, 441), (1227, 693))),
        Edge("proposals", "review_files", "#bb5b54", source_side="left", target_side="right", source_pos=0.72, target_pos=0.72, dashed=True, vias=((1580, 514), (1580, 790), (380, 790), (380, 660))),
    ]
    notes = [
        Node("deploy_rule", "Deployment shape\nMNO is local-first: desktop, HTTP runtime, MCP, review artifacts, logs, and the WSS scratchpad_ephemeral sidecar stay inside the local workspace.", 515, 875, 930, 78, "note", 17, True)
    ]
    return Diagram(
        "mno-architecture-deployment-process",
        "MNO Architecture - Deployment And Process Model",
        "The local process layout for setup, import/build/review, runtime launch, MCP, adapters, and governed outputs.",
        1960,
        1100,
        lanes,
        nodes,
        edges,
        notes,
        [],
        common_legend(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--strict", action="store_true", help="fail if a connector crosses a non-endpoint node or reuses an arrow target")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    all_warnings: list[str] = []

    for diagram in diagrams():
        warnings = validate_diagram(diagram)
        all_warnings.extend(warnings)
        svg = out_dir / f"{diagram.slug}.svg"
        png = out_dir / f"{diagram.slug}.png"
        render_svg(diagram, svg)
        render_png(diagram, png)
        print(f"exported {svg.relative_to(REPO_ROOT)}")
        print(f"exported {png.relative_to(REPO_ROOT)}")

    if all_warnings:
        for warning in all_warnings:
            print(f"warning: {warning}")
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
