#!/usr/bin/env python3
"""Render the repo's plain draw.io flowcharts to SVG and PNG.

This intentionally supports the small mxGraph subset used by docs/visuals:
swimlane backgrounds, rounded rectangles, orthogonal connector arrows, and
wrapped text labels. It is not a general draw.io replacement.
"""

from __future__ import annotations

import argparse
import html
import math
import heapq
from collections import defaultdict, deque
import re
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DRAWIO = [
    REPO_ROOT / "docs" / "visuals" / "MNO_LAUNCH_PIPELINE_2026-04-12.drawio",
    REPO_ROOT / "docs" / "visuals" / "MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio",
    REPO_ROOT / "docs" / "visuals" / "MNO_CURRENT_PIPELINE_2026-04-12.drawio",
    REPO_ROOT / "docs" / "visuals" / "MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio",
    REPO_ROOT / "docs" / "visuals" / "MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18.drawio",
]
DEFAULT_OUT = REPO_ROOT / "docs" / "visuals" / "exports"
FONT_FAMILY = "Segoe UI, Inter, Arial, sans-serif"


@dataclass(frozen=True)
class Box:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    style: dict[str, str]
    lane: bool = False


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    style: dict[str, str]


@dataclass(frozen=True)
class Route:
    edge: Edge
    points: list[tuple[float, float]]
    stroke: str


@dataclass(frozen=True)
class Page:
    source_name: str
    index: int
    name: str
    width: int
    height: int
    boxes: list[Box]
    edges: list[Edge]


def parse_style(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip()] = value.strip()
        else:
            out[part.strip()] = "1"
    return out


def clean_label(raw: str | None) -> str:
    text = str(raw or "")
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"</?(div|p|span|b|strong|i|em)[^>]*>", "", text, flags=re.I)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-+", "-", lowered).strip("-")
    return lowered or "diagram"


def as_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def load_pages(path: Path) -> list[Page]:
    root = ET.parse(path).getroot()
    pages: list[Page] = []
    for index, diagram in enumerate(root.findall("diagram"), start=1):
        graph = diagram.find("mxGraphModel")
        if graph is None:
            continue
        root_node = graph.find("root")
        if root_node is None:
            continue

        boxes: list[Box] = []
        edges: list[Edge] = []
        for cell in root_node.findall("mxCell"):
            style = parse_style(cell.get("style"))
            if cell.get("vertex") == "1":
                geometry = cell.find("mxGeometry")
                if geometry is None:
                    continue
                box = Box(
                    id=str(cell.get("id") or ""),
                    label=clean_label(cell.get("value")),
                    x=as_float(geometry.get("x")),
                    y=as_float(geometry.get("y")),
                    w=max(1.0, as_float(geometry.get("width"), 1.0)),
                    h=max(1.0, as_float(geometry.get("height"), 1.0)),
                    style=style,
                    lane="swimlane" in style,
                )
                boxes.append(box)
            elif cell.get("edge") == "1":
                source = str(cell.get("source") or "")
                target = str(cell.get("target") or "")
                if source and target:
                    edges.append(Edge(id=str(cell.get("id") or ""), source=source, target=target, style=style))

        page_width = int(as_float(graph.get("pageWidth"), 1600))
        page_height = int(as_float(graph.get("pageHeight"), 980))
        if boxes:
            max_x = max(box.x + box.w for box in boxes)
            max_y = max(box.y + box.h for box in boxes)
            page_width = max(page_width, int(math.ceil(max_x + 40)))
            page_height = max(page_height, int(math.ceil(max_y + 40)))

        pages.append(
            Page(
                source_name=path.stem,
                index=index,
                name=str(diagram.get("name") or f"Page {index}"),
                width=page_width,
                height=page_height,
                boxes=boxes,
                edges=edges,
            )
        )
    return pages


def color(style: dict[str, str], key: str, fallback: str) -> str:
    value = style.get(key) or fallback
    if value == "none":
        return fallback
    return value


def font_paths() -> tuple[Path | None, Path | None]:
    candidates = [
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    regular = next((path for path in candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), regular)
    return regular, bold


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    regular, bold_path = font_paths()
    target = bold_path if bold else regular
    if target is not None:
        return ImageFont.truetype(str(target), size=size)
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    if not text:
        return 0.0
    box = draw.textbbox((0, 0), text, font=font)
    return float(box[2] - box[0])


def wrap_lines_pil(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        words = raw_line.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width(draw, candidate, font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def wrap_lines_svg(text: str, width: float, size: int) -> list[str]:
    chars = max(12, int(width / max(7, size * 0.56)))
    out: list[str] = []
    for raw_line in text.split("\n"):
        wrapped = textwrap.wrap(raw_line, width=chars, break_long_words=False) or [""]
        out.extend(wrapped)
    return out


def layout_label(text: str, width: float, height: float, preferred_size: int, *, bold: bool = False) -> tuple[int, list[str], float]:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))
    max_width = max(24.0, width - 24)
    max_height = max(20.0, height - 16)
    for size in range(preferred_size, 8, -1):
        font = load_font(size, bold=bold)
        lines = wrap_lines_pil(probe, text, font, max_width)
        line_height = max(11.0, size * 1.18)
        if len(lines) * line_height <= max_height:
            return size, lines, line_height
    font = load_font(9, bold=bold)
    lines = wrap_lines_pil(probe, text, font, max_width)
    return 9, lines, 10.5


def port(box: Box, style: dict[str, str], prefix: str) -> tuple[float, float]:
    px = as_float(style.get(f"{prefix}X"), 0.5)
    py = as_float(style.get(f"{prefix}Y"), 0.5)
    return box.x + (box.w * px), box.y + (box.h * py)


def edge_path(edge: Edge, boxes_by_id: dict[str, Box]) -> list[tuple[float, float]]:
    source = boxes_by_id[edge.source]
    target = boxes_by_id[edge.target]
    start = port(source, edge.style, "exit")
    end = port(target, edge.style, "entry")
    sx, sy = start
    ex, ey = end
    if abs(sx - ex) < 8 or abs(sy - ey) < 8:
        return [start, end]
    exit_y = as_float(edge.style.get("exitY"), 0.5)
    entry_y = as_float(edge.style.get("entryY"), 0.5)
    if exit_y in {0.0, 1.0} or entry_y in {0.0, 1.0}:
        mid_y = sy + ((ey - sy) / 2.0)
        return [start, (sx, mid_y), (ex, mid_y), end]
    mid_x = sx + ((ex - sx) / 2.0)
    return [start, (mid_x, sy), (mid_x, ey), end]


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


def infer_side(source: Box, target: Box, *, target_role: bool = False) -> str:
    sx = source.x + source.w / 2
    sy = source.y + source.h / 2
    tx = target.x + target.w / 2
    ty = target.y + target.h / 2
    dx = tx - sx
    dy = ty - sy
    if abs(dx) >= abs(dy):
        side = "right" if dx >= 0 else "left"
    else:
        side = "bottom" if dy >= 0 else "top"
    if target_role:
        return {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[side]
    return side


def side_from_style(
    style: dict[str, str],
    prefix: str,
    box: Box,
    other: Box,
    *,
    target_role: bool = False,
    honor_style: bool = True,
) -> str:
    if not honor_style:
        return infer_side(box, other, target_role=target_role)
    x_key = f"{prefix}X"
    y_key = f"{prefix}Y"
    if x_key not in style and y_key not in style:
        return infer_side(box, other, target_role=target_role)
    x = as_float(style.get(x_key), 0.5)
    y = as_float(style.get(y_key), 0.5)
    distances = {
        "left": abs(x - 0.0),
        "right": abs(x - 1.0),
        "top": abs(y - 0.0),
        "bottom": abs(y - 1.0),
    }
    return min(distances, key=distances.get)


def outward(point: tuple[float, float], side: str, amount: float) -> tuple[float, float]:
    x, y = point
    if side == "left":
        return x - amount, y
    if side == "right":
        return x + amount, y
    if side == "top":
        return x, y - amount
    return x, y + amount


def distributed_ports(page: Page, *, honor_style: bool = True) -> dict[tuple[str, str], tuple[tuple[float, float], str]]:
    boxes = {box.id: box for box in page.boxes}
    grouped: dict[tuple[str, str], list[tuple[str, str, tuple[float, float]]]] = defaultdict(list)
    sides: dict[tuple[str, str], str] = {}
    for edge in page.edges:
        if edge.source not in boxes or edge.target not in boxes:
            continue
        source = boxes[edge.source]
        target = boxes[edge.target]
        source_side = side_from_style(edge.style, "exit", source, target, target_role=False, honor_style=honor_style)
        target_side = side_from_style(edge.style, "entry", target, source, target_role=True, honor_style=honor_style)
        sides[(edge.id, "source")] = source_side
        sides[(edge.id, "target")] = target_side
        grouped[(edge.source, source_side)].append((edge.id, "source", (target.x + target.w / 2, target.y + target.h / 2)))
        grouped[(edge.target, target_side)].append((edge.id, "target", (source.x + source.w / 2, source.y + source.h / 2)))

    ports: dict[tuple[str, str], tuple[tuple[float, float], str]] = {}
    for (box_id, side), rows in grouped.items():
        box = boxes[box_id]
        sort_index = 0 if side in {"top", "bottom"} else 1
        rows = sorted(rows, key=lambda row: (row[2][sort_index], row[0], row[1]))
        usable_w = max(1.0, box.w - 44)
        usable_h = max(1.0, box.h - 36)
        for index, (edge_id, role, _other) in enumerate(rows):
            frac = 0.5 if len(rows) == 1 else (index + 1) / (len(rows) + 1)
            if side == "top":
                point = (box.x + 22 + usable_w * frac, box.y)
            elif side == "bottom":
                point = (box.x + 22 + usable_w * frac, box.y + box.h)
            elif side == "left":
                point = (box.x, box.y + 18 + usable_h * frac)
            else:
                point = (box.x + box.w, box.y + 18 + usable_h * frac)
            ports[(edge_id, role)] = (point, side)
    return ports


def simplify_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    deduped: list[tuple[float, float]] = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    simplified: list[tuple[float, float]] = [deduped[0]]
    for idx in range(1, len(deduped) - 1):
        ax, ay = simplified[-1]
        bx, by = deduped[idx]
        cx, cy = deduped[idx + 1]
        if (abs(ax - bx) < 0.01 and abs(bx - cx) < 0.01) or (abs(ay - by) < 0.01 and abs(by - cy) < 0.01):
            continue
        simplified.append((bx, by))
    simplified.append(deduped[-1])
    return simplified


def route_grid_path(
    page: Page,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    obstacles: list[tuple[float, float, float, float]],
    usage: dict[tuple[int, int], int],
    step: int = 16,
) -> list[tuple[float, float]]:
    max_x = max(1, int(math.ceil(page.width / step)))
    max_y = max(1, int(math.ceil(page.height / step)))

    def to_grid(point: tuple[float, float]) -> tuple[int, int]:
        x = max(0, min(max_x, int(round(point[0] / step))))
        y = max(0, min(max_y, int(round(point[1] / step))))
        return x, y

    def to_point(node: tuple[int, int]) -> tuple[float, float]:
        return float(node[0] * step), float(node[1] * step)

    def blocked(node: tuple[int, int]) -> bool:
        x, y = to_point(node)
        for x1, y1, x2, y2 in obstacles:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return True
        return False

    def nearest_free(node: tuple[int, int]) -> tuple[int, int]:
        if not blocked(node):
            return node
        seen = {node}
        queue: deque[tuple[int, int]] = deque([node])
        while queue:
            x, y = queue.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nx < 0 or ny < 0 or nx > max_x or ny > max_y or (nx, ny) in seen:
                    continue
                candidate = (nx, ny)
                if not blocked(candidate):
                    return candidate
                seen.add(candidate)
                queue.append(candidate)
        return node

    start_node = nearest_free(to_grid(start))
    end_node = nearest_free(to_grid(end))
    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    def heuristic(node: tuple[int, int]) -> float:
        return abs(node[0] - end_node[0]) + abs(node[1] - end_node[1])

    start_state = (start_node[0], start_node[1], -1)
    heap: list[tuple[float, float, tuple[int, int, int]]] = [(heuristic(start_node), 0.0, start_state)]
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    cost_so_far: dict[tuple[int, int, int], float] = {start_state: 0.0}
    final_state: tuple[int, int, int] | None = None

    while heap:
        _priority, cost_so_far_state, current = heapq.heappop(heap)
        cx, cy, cdir = current
        if (cx, cy) == end_node:
            final_state = current
            break
        if cost_so_far_state > cost_so_far.get(current, float("inf")):
            continue
        for direction_index, (dx, dy) in enumerate(directions):
            nx = cx + dx
            ny = cy + dy
            if nx < 0 or ny < 0 or nx > max_x or ny > max_y:
                continue
            neighbor_node = (nx, ny)
            if blocked(neighbor_node):
                continue
            turn_penalty = 0.0 if cdir in {-1, direction_index} else 0.55
            reuse_penalty = min(8.0, usage.get(neighbor_node, 0) * 2.2)
            edge_bias = 0.12 if nx in {0, max_x} or ny in {0, max_y} else 0.0
            new_cost = cost_so_far_state + 1.0 + turn_penalty + reuse_penalty + edge_bias
            neighbor_state = (nx, ny, direction_index)
            if new_cost < cost_so_far.get(neighbor_state, float("inf")):
                cost_so_far[neighbor_state] = new_cost
                priority = new_cost + heuristic(neighbor_node)
                heapq.heappush(heap, (priority, new_cost, neighbor_state))
                came_from[neighbor_state] = current

    if final_state is None:
        sx, sy = start
        ex, ey = end
        if abs(sx - ex) > abs(sy - ey):
            mid = (sx + (ex - sx) / 2, sy)
            return simplify_path([start, mid, (mid[0], ey), end])
        mid = (sx, sy + (ey - sy) / 2)
        return simplify_path([start, mid, (ex, mid[1]), end])

    states = [final_state]
    while states[-1] != start_state:
        states.append(came_from[states[-1]])
    states.reverse()
    routed = [to_point((x, y)) for x, y, _direction in states]
    return simplify_path(routed)


def build_routes(page: Page, *, honor_style: bool = True) -> list[Route]:
    boxes = {box.id: box for box in page.boxes}
    ports = distributed_ports(page, honor_style=honor_style)
    usage: dict[tuple[int, int], int] = defaultdict(int)
    routes: list[Route] = []
    pad = 18.0
    grid_step = 16
    node_boxes = [box for box in page.boxes if not box.lane]

    for edge in sorted(page.edges, key=lambda item: item.id):
        if edge.source not in boxes or edge.target not in boxes:
            continue
        source = boxes[edge.source]
        target = boxes[edge.target]
        source_port, source_side = ports.get((edge.id, "source"), (port(source, edge.style, "exit"), infer_side(source, target)))
        target_port, target_side = ports.get((edge.id, "target"), (port(target, edge.style, "entry"), infer_side(target, source, target_role=True)))
        start = outward(source_port, source_side, 28.0)
        end = outward(target_port, target_side, 28.0)
        obstacles = [
            (box.x - pad, box.y - pad, box.x + box.w + pad, box.y + box.h + pad)
            for box in node_boxes
            if box.id not in {source.id, target.id}
        ]
        inner = route_grid_path(page, start, end, obstacles=obstacles, usage=usage, step=grid_step)
        points = simplify_path([source_port, start, *inner, end, target_port])
        for x, y in inner:
            usage[(int(round(x / grid_step)), int(round(y / grid_step)))] += 1
        routes.append(Route(edge=edge, points=points, stroke=color(edge.style, "strokeColor", "#6b7280")))
    return routes


def svg_text(label: str, x: float, y: float, width: float, height: float, size: int, *, bold: bool = False) -> str:
    size, lines, line_height = layout_label(label, width, height, size, bold=bold)
    total = len(lines) * line_height
    start_y = y + max(size + 6, (height - total) / 2 + size)
    weight = "700" if bold else "500"
    escaped_lines = []
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else line_height
        escaped_lines.append(
            f'<tspan x="{x + width / 2:.1f}" dy="{dy:.1f}">{html.escape(line)}</tspan>'
        )
    return (
        f'<text text-anchor="middle" font-family="{FONT_FAMILY}" font-size="{size}" '
        f'font-weight="{weight}" fill="#1f2933" x="{x + width / 2:.1f}" y="{start_y:.1f}">'
        f'{"".join(escaped_lines)}</text>'
    )


def label_height(label: str, width: float, preferred_size: int = 16) -> float:
    size, lines, line_height = layout_label(label, width, 1000.0, preferred_size)
    return max(74.0, len(lines) * line_height + size + 30.0)


def relayout_page(page: Page) -> Page:
    lanes = sorted([box for box in page.boxes if box.lane], key=lambda item: item.x)
    nodes = [box for box in page.boxes if not box.lane]
    if not lanes:
        return relayout_freeform_page(page, nodes)

    margin = 42.0
    gutter = 76.0
    lane_padding_x = 44.0
    lane_padding_y = 82.0
    node_gap = 42.0
    column_width = 430.0 if len(lanes) >= 4 else 460.0
    node_width = column_width - lane_padding_x * 2

    lane_by_id = {lane.id: lane for lane in lanes}
    lane_nodes: dict[str, list[Box]] = {lane.id: [] for lane in lanes}
    spanning: list[Box] = []

    for node in nodes:
        center_x = node.x + node.w / 2
        center_y = node.y + node.h / 2
        containing = [
            lane
            for lane in lanes
            if lane.x <= center_x <= lane.x + lane.w and lane.y <= center_y <= lane.y + lane.h
        ]
        if node.w > max(lane.w for lane in lanes) * 1.35:
            spanning.append(node)
            continue
        lane = containing[0] if containing else min(lanes, key=lambda item: abs((item.x + item.w / 2) - center_x))
        lane_nodes[lane.id].append(node)

    new_lanes: list[Box] = []
    new_nodes: list[Box] = []
    lane_bottoms: list[float] = []
    lane_x: dict[str, float] = {}

    for lane_index, lane in enumerate(lanes):
        x = margin + lane_index * (column_width + gutter)
        lane_x[lane.id] = x
        y = margin
        cursor = y + lane_padding_y
        sorted_nodes = sorted(lane_nodes[lane.id], key=lambda item: (item.y, item.x, item.id))
        for node in sorted_nodes:
            h = label_height(node.label, node_width)
            new_nodes.append(
                Box(
                    id=node.id,
                    label=node.label,
                    x=x + lane_padding_x,
                    y=cursor,
                    w=node_width,
                    h=h,
                    style=node.style,
                    lane=False,
                )
            )
            cursor += h + node_gap
        lane_bottoms.append(cursor + lane_padding_y / 2)
        new_lanes.append(
            Box(
                id=lane.id,
                label=lane.label,
                x=x,
                y=y,
                w=column_width,
                h=1.0,
                style=lane.style,
                lane=True,
            )
        )

    common_lane_height = max(lane_bottoms) - margin if lane_bottoms else 900.0
    relaid_lanes = [
        Box(id=lane.id, label=lane.label, x=lane.x, y=lane.y, w=lane.w, h=common_lane_height, style=lane.style, lane=True)
        for lane in new_lanes
    ]

    page_width = int(math.ceil(margin * 2 + len(lanes) * column_width + max(0, len(lanes) - 1) * gutter))
    cursor = margin + common_lane_height + 42.0
    for node in sorted(spanning, key=lambda item: (item.y, item.x, item.id)):
        w = min(page_width - margin * 2 - 120.0, max(780.0, node.w))
        h = label_height(node.label, w, preferred_size=16)
        new_nodes.append(
            Box(
                id=node.id,
                label=node.label,
                x=(page_width - w) / 2,
                y=cursor,
                w=w,
                h=h,
                style=node.style,
                lane=False,
            )
        )
        cursor += h + 34.0

    page_height = int(math.ceil(max(cursor + margin, margin + common_lane_height + margin)))
    return Page(
        source_name=page.source_name,
        index=page.index,
        name=page.name,
        width=page_width,
        height=page_height,
        boxes=[*relaid_lanes, *new_nodes],
        edges=page.edges,
    )


def leading_number(label: str) -> int | None:
    match = re.match(r"\s*(\d+)\.", label)
    if not match:
        return None
    return int(match.group(1))


def relayout_freeform_page(page: Page, nodes: list[Box]) -> Page:
    if not nodes:
        return page
    ordered = sorted(nodes, key=lambda item: (leading_number(item.label) is None, leading_number(item.label) or 9999, item.y, item.x))
    count = len(ordered)
    cols = 4 if count >= 8 else 3
    node_width = 360.0
    margin_x = 70.0
    margin_y = 70.0
    col_gap = 90.0
    row_gap = 155.0
    row_heights: dict[int, float] = {}
    placements: list[tuple[Box, int, int]] = []
    for index, node in enumerate(ordered):
        row = index // cols
        col = index % cols
        if row % 2 == 1:
            col = cols - 1 - col
        h = label_height(node.label, node_width, preferred_size=15)
        row_heights[row] = max(row_heights.get(row, 0.0), h)
        placements.append((node, row, col))

    row_y: dict[int, float] = {}
    cursor = margin_y
    for row in range(max(row_heights) + 1):
        row_y[row] = cursor
        cursor += row_heights[row] + row_gap

    new_nodes: list[Box] = []
    for node, row, col in placements:
        x = margin_x + col * (node_width + col_gap)
        y = row_y[row]
        new_nodes.append(
            Box(
                id=node.id,
                label=node.label,
                x=x,
                y=y,
                w=node_width,
                h=row_heights[row],
                style=node.style,
                lane=False,
            )
        )
    page_width = int(math.ceil(margin_x * 2 + cols * node_width + (cols - 1) * col_gap))
    page_height = int(math.ceil(cursor + margin_y))
    return Page(
        source_name=page.source_name,
        index=page.index,
        name=page.name,
        width=page_width,
        height=page_height,
        boxes=new_nodes,
        edges=page.edges,
    )


def render_svg(page: Page, out_path: Path) -> None:
    page = relayout_page(page)
    routes = build_routes(page, honor_style=False)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{page.width}" height="{page.height}" '
            f'viewBox="0 0 {page.width} {page.height}" role="img" aria-label="{html.escape(page.name)}">'
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    for box in [item for item in page.boxes if item.lane]:
        fill = color(box.style, "fillColor", "#f7fafc")
        stroke = color(box.style, "strokeColor", "#9aa5b1")
        parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="8" fill="{fill}" fill-opacity="0.48" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{box.x + 16:.1f}" y="{box.y + 27:.1f}" font-family="{FONT_FAMILY}" '
            f'font-size="17" font-weight="700" fill="#243b53">{html.escape(box.label)}</text>'
        )

    arrowheads: list[tuple[str, list[tuple[float, float]]]] = []
    for route in routes:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in route.points)
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{route.stroke}" stroke-width="2.4" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        if len(route.points) >= 2:
            arrowheads.append((route.stroke, arrow_points(route.points[-2], route.points[-1])))

    for box in [item for item in page.boxes if not item.lane]:
        fill = color(box.style, "fillColor", "#ffffff")
        stroke = color(box.style, "strokeColor", "#52616b")
        rounded = box.style.get("rounded") == "1"
        rx = 12 if rounded else 4
        parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        size = 14 if box.w >= 220 else 12
        parts.append(svg_text(box.label, box.x + 10, box.y + 5, box.w - 20, box.h - 10, size))

    for stroke, arrow in arrowheads:
        arrow_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in arrow)
        parts.append(f'<polygon points="{arrow_text}" fill="{stroke}"/>')

    parts.append("</svg>")
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def render_png(page: Page, out_path: Path, *, scale: int = 2) -> None:
    page = relayout_page(page)
    image = Image.new("RGB", (page.width * scale, page.height * scale), "white")
    draw = ImageDraw.Draw(image)

    def s(value: float) -> int:
        return int(round(value * scale))

    routes = build_routes(page, honor_style=False)

    for box in [item for item in page.boxes if item.lane]:
        fill = color(box.style, "fillColor", "#f7fafc")
        stroke = color(box.style, "strokeColor", "#9aa5b1")
        draw.rounded_rectangle([s(box.x), s(box.y), s(box.x + box.w), s(box.y + box.h)], radius=s(8), fill=fill, outline=stroke, width=s(2))
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            [s(box.x), s(box.y), s(box.x + box.w), s(box.y + box.h)],
            radius=s(8),
            fill=(255, 255, 255, 96),
        )
        image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
        font = load_font(17 * scale, bold=True)
        draw = ImageDraw.Draw(image)
        draw.text((s(box.x + 16), s(box.y + 9)), box.label, font=font, fill="#243b53")

    arrowheads_png: list[tuple[str, list[tuple[int, int]]]] = []
    for route in routes:
        scaled_path = [(s(x), s(y)) for x, y in route.points]
        draw.line(scaled_path, fill=route.stroke, width=s(2.4), joint="curve")
        if len(route.points) >= 2:
            arrowheads_png.append((route.stroke, [(s(x), s(y)) for x, y in arrow_points(route.points[-2], route.points[-1], size=12)]))

    for box in [item for item in page.boxes if not item.lane]:
        fill = color(box.style, "fillColor", "#ffffff")
        stroke = color(box.style, "strokeColor", "#52616b")
        radius = 12 if box.style.get("rounded") == "1" else 4
        draw.rounded_rectangle([s(box.x), s(box.y), s(box.x + box.w), s(box.y + box.h)], radius=s(radius), fill=fill, outline=stroke, width=s(2))
        preferred = 14 if box.w >= 220 else 12
        font_size, lines, line_height_raw = layout_label(box.label, box.w - 20, box.h - 10, preferred)
        font = load_font(font_size * scale, bold=False)
        line_height = int(line_height_raw * scale)
        total_h = line_height * len(lines)
        y = s(box.y) + max(s(10), int(((box.h * scale) - total_h) / 2))
        for line in lines:
            width = text_width(draw, line, font)
            x = s(box.x + box.w / 2) - int(width / 2)
            draw.text((x, y), line, font=font, fill="#1f2933")
            y += line_height

    for stroke, arrow in arrowheads_png:
        draw.polygon(arrow, fill=stroke)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG", optimize=True)


def render_page(page: Page, out_dir: Path) -> tuple[Path, Path]:
    stem = f"{page.source_name}__p{page.index:02d}_{slugify(page.name)}"
    svg_path = out_dir / f"{stem}.svg"
    png_path = out_dir / f"{stem}.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    render_svg(page, svg_path)
    render_png(page, png_path)
    return svg_path, png_path


def default_inputs(paths: Iterable[str]) -> list[Path]:
    if paths:
        return [Path(item).expanduser().resolve() for item in paths]
    return CANONICAL_DRAWIO


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drawio", nargs="*", help="draw.io files to export. Defaults to the canonical visuals.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT), help="Output directory for SVG and PNG assets.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    exported: list[tuple[Path, Path]] = []
    for path in default_inputs(args.drawio):
        if not path.exists():
            raise FileNotFoundError(path)
        for page in load_pages(path):
            exported.append(render_page(page, out_dir))

    for svg_path, png_path in exported:
        print(f"exported {svg_path.relative_to(REPO_ROOT)}")
        print(f"exported {png_path.relative_to(REPO_ROOT)}")
    print(f"rendered_pages={len(exported)} out_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
