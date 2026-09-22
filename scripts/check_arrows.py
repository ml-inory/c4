#!/usr/bin/env python3
"""Check relationship arrows and their labels in rendered C4 diagrams.

Usage:
    python3 check_arrows.py docs/c4/diagrams/*.mmd [--svg-dir docs/c4/svg] [--json]

`check_layout.py` measures whether text collides with text or with a box. It does
not measure the thing readers complain about most: several arrows converging or
crossing, with labels whose owner is impossible to tell. This checker pairs each
relationship in the `.mmd` source with its drawn connector in the SVG and then
reports:

  label-foreign    the label is closer to another relationship's arrow than to
                   its own - the reader will attach it to the wrong arrow
  label-ambiguous  the label is nearly equidistant from two arrows
  label-detached   the label sits far from its own arrow
  label-on-arrow   the label's own arrow is drawn through the text
  label-crossed    another relationship's arrow runs through the label box
  edge-overlap     two arrows are drawn along the same path, so the reader sees
                   one line where the model has two relationships
  edge-bundle      two arrows run parallel and closer together than the eye can
                   separate for a sustained stretch
  edge-through-box an arrow passes underneath an element box or a boundary
  shared-arrowhead two arrows arrive at the same point of the same element, so
                   their heads cannot be told apart
  edge-crossings   more arrows cross than the configured budget allows
  fan-in           more arrows meet one element than the budget allows
  unmatched-edge   a relationship could not be paired with a drawn connector

Exit code is 1 when any error-level problem is found (every kind above except
none), otherwise 0.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import check_layout as CL

NS = "{http://www.w3.org/2000/svg}"

ELEMENT_RE = re.compile(
    r'^\s*(Person|System|Container|Component|Deployment_Node|Node\w*|Boundary)\w*'
    r'\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)"\s*)?(?:,\s*"([^"]*)"\s*)?\)',
    re.M,
)
REL_RE = re.compile(
    r'^\s*(BiRel\w*|Rel_Back|Rel_\w+|Rel)\(\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?',
    re.M,
)

MAX_LABEL_DISTANCE = 30.0
AMBIGUITY_MARGIN = 3.0
MAX_CROSSINGS = 2
MAX_FAN_IN = 3
OVERLAP_TOLERANCE = 2.5
MAX_OVERLAP_LENGTH = 16.0
PARALLEL_DISTANCE = 8.0
MAX_PARALLEL_LENGTH = 60.0
ARROWHEAD_DISTANCE = 12.0
BOX_MARGIN = 1.0


def parse_source(path: Path) -> Tuple[Dict[str, Tuple[str, str]], List[Tuple[str, str, str, str]], bool]:
    """Return (alias -> (name, description), relationships, is_sequence)."""
    source = path.read_text(encoding="utf-8")
    elements: Dict[str, Tuple[str, str]] = {}
    for match in ELEMENT_RE.finditer(source):
        keyword, alias, name, tech, description = match.groups()
        # Person()/System() have no technology argument; Container()/Component() do.
        text = tech if description is None else description
        elements[alias] = (name, (text or "").strip())
    relationships: List[Tuple[str, str, str, str]] = []
    for match in REL_RE.finditer(source):
        keyword, source_alias, target_alias, label, tech = match.groups()
        if keyword.startswith("Rel_Back"):
            source_alias, target_alias = target_alias, source_alias
        relationships.append((source_alias, target_alias, label, tech or ""))
    return elements, relationships, "sequenceDiagram" in source


def parent_map(root) -> Dict[object, object]:
    return {child: parent for parent in root.iter() for child in parent}


def absolute_translate(node, parents: Dict[object, object]) -> Tuple[float, float]:
    dx = dy = 0.0
    current = node
    while current is not None:
        tx, ty = CL.parse_translate(current)
        dx += tx
        dy += ty
        current = parents.get(current)
    return dx, dy


def _numbers(raw: str) -> List[float]:
    return [float(value) for value in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", raw)]


def sample_path(d: str, per_segment: int = 24) -> List[Tuple[float, float]]:
    """Sample an SVG path into points, supporting the commands Mermaid emits."""
    points: List[Tuple[float, float]] = []
    cursor = (0.0, 0.0)
    start = (0.0, 0.0)
    for command, raw in re.findall(r"([A-Za-z])([^A-Za-z]*)", d):
        values = _numbers(raw)
        if command in "Mm":
            pairs = list(zip(values[0::2], values[1::2]))
            for x, y in pairs:
                cursor = (x, y) if command == "M" else (cursor[0] + x, cursor[1] + y)
                points.append(cursor)
                start = cursor
        elif command in "LlHhVv":
            for index in range(0, len(values), 2 if command in "Ll" else 1):
                if command in "Ll":
                    x, y = values[index], values[index + 1]
                elif command in "Hh":
                    x, y = values[index], cursor[1]
                else:
                    x, y = cursor[0], values[index]
                target = (x, y) if command.isupper() else (cursor[0] + x, cursor[1] + y)
                for step in range(1, per_segment + 1):
                    t = step / per_segment
                    points.append((cursor[0] + (target[0] - cursor[0]) * t, cursor[1] + (target[1] - cursor[1]) * t))
                cursor = target
        elif command in "Qq":
            for index in range(0, len(values), 4):
                cx, cy, x, y = values[index:index + 4]
                if command == "q":
                    cx, cy = cursor[0] + cx, cursor[1] + cy
                    x, y = cursor[0] + x, cursor[1] + y
                for step in range(1, per_segment + 1):
                    t = step / per_segment
                    inv = 1 - t
                    points.append(
                        (
                            inv * inv * cursor[0] + 2 * inv * t * cx + t * t * x,
                            inv * inv * cursor[1] + 2 * inv * t * cy + t * t * y,
                        )
                    )
                cursor = (x, y)
        elif command in "Cc":
            for index in range(0, len(values), 6):
                c1x, c1y, c2x, c2y, x, y = values[index:index + 6]
                if command == "c":
                    c1x, c1y = cursor[0] + c1x, cursor[1] + c1y
                    c2x, c2y = cursor[0] + c2x, cursor[1] + c2y
                    x, y = cursor[0] + x, cursor[1] + y
                for step in range(1, per_segment + 1):
                    t = step / per_segment
                    inv = 1 - t
                    points.append(
                        (
                            inv**3 * cursor[0] + 3 * inv * inv * t * c1x + 3 * inv * t * t * c2x + t**3 * x,
                            inv**3 * cursor[1] + 3 * inv * inv * t * c1y + 3 * inv * t * t * c2y + t**3 * y,
                        )
                    )
                cursor = (x, y)
        elif command in "Zz":
            cursor = start
        elif command in "Aa":
            # Arcs are not used by Mermaid C4 edges; approximate with a straight line.
            for index in range(0, len(values), 7):
                x, y = values[index + 5], values[index + 6]
                target = (x, y) if command == "A" else (cursor[0] + x, cursor[1] + y)
                for step in range(1, per_segment + 1):
                    t = step / per_segment
                    points.append((cursor[0] + (target[0] - cursor[0]) * t, cursor[1] + (target[1] - cursor[1]) * t))
                cursor = target
    return points


def collect_edges(root, parents) -> List[List[Tuple[float, float]]]:
    edges: List[List[Tuple[float, float]]] = []
    for node in root.iter():
        tag = node.tag.replace(NS, "")
        if tag not in ("line", "path"):
            continue
        if not node.get("marker-end"):
            continue
        ox, oy = absolute_translate(node, parents)
        if tag == "line":
            x1 = CL.number(node.get("x1")) or 0.0
            y1 = CL.number(node.get("y1")) or 0.0
            x2 = CL.number(node.get("x2")) or 0.0
            y2 = CL.number(node.get("y2")) or 0.0
            points = [
                (ox + x1 + (x2 - x1) * step / 24, oy + y1 + (y2 - y1) * step / 24) for step in range(25)
            ]
        else:
            raw = node.get("d")
            if not raw:
                continue
            points = [(ox + x, oy + y) for x, y in sample_path(raw)]
        if len(points) >= 2:
            edges.append(points)
    return edges


def point_to_box_distance(point: Tuple[float, float], box: Tuple[float, float, float, float]) -> float:
    x, y = point
    x0, y0, x1, y1 = box
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def point_to_box_inside(point: Tuple[float, float], box: Tuple[float, float, float, float]) -> bool:
    x, y = point
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def point_to_bbox_distance(point: Tuple[float, float], bbox) -> float:
    return point_to_box_distance(point, bbox)


def collect_boxes(
    root, parents, elements
) -> Tuple[List[Tuple[str, Tuple[float, float, float, float]]], List[Tuple[float, float, float, float]]]:
    """Return ((alias, rect) per element shape, every shape rect).

    A shape is identified by the text inside it: its element name followed, before
    the next element name, by its technology and description. The name alone is not
    enough, because two containers can share a name - `ax_comm.ko` exists once on
    the host and once on the device.
    """
    by_name: Dict[str, List[str]] = {}
    for alias, (name, _text) in elements.items():
        by_name.setdefault(name, []).append(alias)
    by_pair: Dict[Tuple[str, str], str] = {
        (name, text): alias for alias, (name, text) in elements.items() if text
    }

    font = CL.load_font()
    boxes: List[Tuple[str, Tuple[float, float, float, float]]] = []
    shape_rects: List[Tuple[float, float, float, float]] = []
    for node in root.iter(NS + "rect"):
        width = CL.number(node.get("width")) or 0.0
        height = CL.number(node.get("height")) or 0.0
        fill = (node.get("fill") or "").upper()
        if width <= 40 or height <= 20 or fill in ("", "NONE", "#FFFFFF", "WHITE"):
            continue
        ox, oy = absolute_translate(node, parents)
        x = CL.number(node.get("x")) or 0.0
        y = CL.number(node.get("y")) or 0.0
        box = (ox + x, oy + y, ox + x + width, oy + y + height)
        shape_rects.append(box)

        alias: Optional[str] = None
        current = parents.get(node)
        while current is not None and alias is None:
            runs: List[CL.Run] = []
            CL.Checker(font, 0).collect_all(current, 0.0, 0.0, runs)
            texts = [run.text for run in runs]
            for name in [candidate for candidate in by_name if candidate in texts]:
                for index, text in enumerate(texts):
                    if text != name:
                        continue
                    for following in texts[index + 1:index + 4]:
                        match = by_pair.get((name, following))
                        if match:
                            alias = match
                            break
                    if alias:
                        break
                if alias:
                    break
            current = parents.get(current)
        if alias:
            boxes.append((alias, box))
    return boxes, shape_rects


def inside_any_box(point: Tuple[float, float], boxes) -> bool:
    return any(point_to_box_inside(point, box) for box in boxes)


def segment_intersection(a, b, c, d) -> Optional[Tuple[float, float]]:
    def cross(px, py, qx, qy):
        return px * qy - py * qx

    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = cross(r[0], r[1], s[0], s[1])
    if abs(denominator) < 1e-9:
        return None
    t = cross(c[0] - a[0], c[1] - a[1], s[0], s[1]) / denominator
    u = cross(c[0] - a[0], c[1] - a[1], r[0], r[1]) / denominator
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def count_crossings(first, second) -> int:
    count = 0
    for index in range(len(first) - 1):
        for other in range(len(second) - 1):
            if segment_intersection(first[index], first[index + 1], second[other], second[other + 1]):
                count += 1
    return count


def nearest_alias(point, boxes) -> Optional[str]:
    best = None
    for alias, box in boxes:
        distance = point_to_box_distance(point, box)
        if best is None or distance < best[0]:
            best = (distance, alias)
    return best[1] if best else None


def point_to_segment_distance(point, a, b) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_to_polyline_distance(point, polyline) -> float:
    return min(
        point_to_segment_distance(point, polyline[index], polyline[index + 1])
        for index in range(len(polyline) - 1)
    )


def close_length(first, second, tolerance: float) -> float:
    """Length of `first` that runs within `tolerance` px of `second`."""
    total = 0.0
    for index in range(len(first) - 1):
        a, b = first[index], first[index + 1]
        segment = math.hypot(b[0] - a[0], b[1] - a[1])
        if segment <= 0.0:
            continue
        midpoint = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if point_to_polyline_distance(midpoint, second) <= tolerance:
            total += segment
    return total


def polyline_inside_box_length(polyline, box) -> float:
    x0, y0, x1, y1 = box
    inner = (x0 + BOX_MARGIN, y0 + BOX_MARGIN, x1 - BOX_MARGIN, y1 - BOX_MARGIN)
    total = 0.0
    for index in range(len(polyline) - 1):
        a, b = polyline[index], polyline[index + 1]
        segment = math.hypot(b[0] - a[0], b[1] - a[1])
        if segment <= 0.0:
            continue
        midpoint = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if point_to_box_inside(midpoint, inner):
            total += segment
    return total


def polyline_through_box_length(polyline, box) -> float:
    """Length of `polyline` that either sits inside `box` or cuts straight across it."""
    x0, y0, x1, y1 = box
    inner = (x0 + BOX_MARGIN, y0 + BOX_MARGIN, x1 - BOX_MARGIN, y1 - BOX_MARGIN)
    total = polyline_inside_box_length(polyline, box)
    if total:
        return total
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for index in range(len(polyline) - 1):
        a, b = polyline[index], polyline[index + 1]
        segment = math.hypot(b[0] - a[0], b[1] - a[1])
        if segment <= 0.0:
            continue
        cuts = sum(
            1
            for corner in range(4)
            if segment_intersection(a, b, corners[corner], corners[(corner + 1) % 4])
        )
        if cuts == 2:
            total += segment
    return total


def label_box_penetration(polyline, bbox, shrink: float = 1.0) -> float:
    """Length of `polyline` that runs through a label box."""
    x0, y0, x1, y1 = bbox
    inner = (x0 + shrink, y0 + shrink, x1 - shrink, y1 - shrink)
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        inner = bbox
    total = 0.0
    for index in range(len(polyline) - 1):
        a, b = polyline[index], polyline[index + 1]
        segment = math.hypot(b[0] - a[0], b[1] - a[1])
        if segment <= 0.0:
            continue
        midpoint = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if point_to_box_inside(midpoint, inner):
            total += segment
    return total


def check_diagram(
    mmd: Path,
    svg: Path,
    max_crossings: int,
    max_fan_in: int,
    max_label_distance: float,
    ambiguity_margin: float = AMBIGUITY_MARGIN,
    overlap_tolerance: float = OVERLAP_TOLERANCE,
    max_overlap_length: float = MAX_OVERLAP_LENGTH,
    parallel_distance: float = PARALLEL_DISTANCE,
    max_parallel_length: float = MAX_PARALLEL_LENGTH,
    arrowhead_distance: float = ARROWHEAD_DISTANCE,
) -> Dict[str, object]:
    elements, relationships, is_sequence = parse_source(mmd)
    report: Dict[str, object] = {"file": str(mmd), "problems": []}
    problems: List[Dict[str, object]] = report["problems"]  # type: ignore[assignment]
    if is_sequence or not relationships:
        report["note"] = "no C4 relationships (sequence or class diagram): arrow checks skipped"
        return report

    root = ET.fromstring(svg.read_text(encoding="utf-8"))
    parents = parent_map(root)
    font = CL.load_font()
    edges = collect_edges(root, parents)
    boxes, shape_rects = collect_boxes(root, parents, elements)

    runs: List[CL.Run] = []
    CL.Checker(font, 0).collect_all(root, 0.0, 0.0, runs)
    unique = {(run.text, round(run.x0, 1), round(run.baseline, 1)): run for run in runs}
    runs = list(unique.values())
    by_text: Dict[str, List[CL.Run]] = {}
    for run in runs:
        by_text.setdefault(run.text, []).append(run)

    # Pair every relationship with its connector: the arrow starts at the source
    # shape and ends at the target shape.
    edge_pairs: List[Tuple[str, str, int]] = []
    for index, points in enumerate(edges):
        edge_pairs.append((nearest_alias(points[0], boxes), nearest_alias(points[-1], boxes), index))

    # A relationship label is drawn as one text run above the line and, when the
    # relationship carries a technology, a second run below it. Measuring against
    # their union would make every label straddle its own arrow and report 0px
    # distances, so keep the runs apart and measure against the nearest one.
    label_boxes: Dict[int, Tuple[List[Tuple[float, float, float, float]], str]] = {}
    used_edges = set()
    for source_alias, target_alias, label, tech in relationships:
        candidates = [
            (index, points)
            for alias_a, alias_b, index in edge_pairs
            if alias_a == source_alias and alias_b == target_alias and index not in used_edges
            for points in [edges[index]]
        ]
        if not candidates and (source_alias, target_alias) != (None, None):
            candidates = [
                (index, edges[index])
                for alias_a, alias_b, index in edge_pairs
                if alias_b == target_alias and index not in used_edges
            ]
        if not candidates:
            problems.append({"kind": "unmatched-edge", "text": label, "relationship": [source_alias, target_alias]})
            continue
        index, _points = candidates[0]
        used_edges.add(index)
        anchors = by_text.get(label, [])
        if not anchors:
            continue
        anchor = max(anchors, key=lambda run: run.baseline)
        # Only technology tags outside every shape belong to this label; an element
        # carries its own technology line, which can be the same string.
        parts = [anchor] + [
            run
            for run in by_text.get("[{}]".format(tech), [])
            if abs(run.baseline - anchor.baseline) < 30
            and not inside_any_box(((run.x0 + run.x1) / 2, (run.y0 + run.y1) / 2), shape_rects)
        ]
        label_boxes[index] = (
            [(part.x0, part.y0, part.x1, part.y1) for part in parts],
            "{} [{}]".format(label, tech) if tech else label,
        )

    # Label ownership: a label must be closest to its own arrow.
    for index, (parts, label) in label_boxes.items():
        own = min(
            min(point_to_box_distance(point, part) for part in parts) for point in edges[index]
        )
        others = [
            (
                min(min(point_to_box_distance(point, part) for part in parts) for point in edges[other]),
                other,
            )
            for other in range(len(edges))
            if other != index
        ]
        foreign = min(others) if others else None
        if own > max_label_distance:
            problems.append(
                {"kind": "label-detached", "text": label, "distance_to_own_arrow": round(own, 1)}
            )
        if foreign and foreign[0] <= own - 1.0:
            problems.append(
                {
                    "kind": "label-foreign",
                    "text": label,
                    "distance_to_own_arrow": round(own, 1),
                    "distance_to_other_arrow": round(foreign[0], 1),
                }
            )
        # Ambiguity means the reader cannot decide: two arrows roughly the same
        # distance away and both close enough to be the owner. A label 2px from its
        # own arrow and 8px from a neighbour is not ambiguous, it is fine.
        elif foreign and foreign[0] - own < ambiguity_margin and foreign[0] <= parallel_distance * 1.5:
            problems.append(
                {
                    "kind": "label-ambiguous",
                    "text": label,
                    "distance_to_own_arrow": round(own, 1),
                    "distance_to_other_arrow": round(foreign[0], 1),
                }
            )

    # Text struck through by its own arrow reads as a cancellation, and text with a
    # foreign arrow through it cannot be attributed reliably.
    for index, (parts, label) in label_boxes.items():
        own_penetration = max(
            (label_box_penetration(edges[index], part, shrink=0.5) for part in parts), default=0.0
        )
        # A line grazing a descender by a pixel or two is not what readers notice;
        # a line drawn through the words is.
        if own_penetration > 6.0:
            problems.append(
                {
                    "kind": "label-on-arrow",
                    "text": label,
                    "penetration": round(own_penetration, 1),
                }
            )
        for other in range(len(edges)):
            if other == index:
                continue
            penetration = max(
                (label_box_penetration(edges[other], part, shrink=0.5) for part in parts),
                default=0.0,
            )
            if penetration > 3.0:
                problems.append(
                    {
                        "kind": "label-crossed-by-arrow",
                        "text": label,
                        "penetration": round(penetration, 1),
                    }
                )
                break

    # Arrow-against-arrow legibility: overlap, tight bundles, shared arrowheads.
    alias_by_edge = {index: (source, target) for source, target, index in edge_pairs}
    overlapped: List[Tuple[int, int, float, float]] = []
    for first in range(len(edges)):
        for second in range(first + 1, len(edges)):
            overlap = close_length(edges[first], edges[second], overlap_tolerance)
            if overlap < max_overlap_length:
                continue
            bundle = close_length(edges[first], edges[second], parallel_distance)
            overlapped.append((first, second, overlap, bundle))
    report["overlapping_pairs"] = len(overlapped)
    for first, second, overlap, bundle in overlapped:
        problems.append(
            {
                "kind": "edge-overlap",
                "arrows": [alias_by_edge.get(first), alias_by_edge.get(second)],
                "overlap_px": round(overlap, 1),
                "bundle_px": round(bundle, 1),
            }
        )

    bundled = 0
    seen_pairs = {(first, second) for first, second, _overlap, _bundle in overlapped}
    for first in range(len(edges)):
        for second in range(first + 1, len(edges)):
            if (first, second) in seen_pairs:
                continue
            overlap = close_length(edges[first], edges[second], overlap_tolerance)
            if overlap >= max_overlap_length:
                continue
            bundle = close_length(edges[first], edges[second], parallel_distance)
            if bundle <= max_parallel_length:
                continue
            shared = (
                math.hypot(
                    edges[first][-1][0] - edges[second][-1][0],
                    edges[first][-1][1] - edges[second][-1][1],
                )
                <= arrowhead_distance
            )
            bundled += 1
            problems.append(
                {
                    "kind": "shared-arrowhead" if shared else "edge-bundle",
                    "arrows": [alias_by_edge.get(first), alias_by_edge.get(second)],
                    "parallel_px": round(bundle, 1),
                    "overlap_px": round(overlap, 1),
                }
            )
    report["bundled_pairs"] = bundled

    # An arrow drawn underneath an element box hides both the box content and the arrow.
    for index, polyline in enumerate(edges):
        source_alias, target_alias = alias_by_edge.get(index, (None, None))
        for alias, box in boxes:
            if alias in (source_alias, target_alias):
                continue
            hidden = polyline_through_box_length(polyline, box)
            if hidden > 12.0:
                problems.append(
                    {
                        "kind": "edge-through-box",
                        "arrows": [source_alias, target_alias],
                        "element": alias,
                        "hidden_px": round(hidden, 1),
                    }
                )
                break

    # Arrow crossings and fan-in.
    crossings = 0
    for first in range(len(edges)):
        for second in range(first + 1, len(edges)):
            crossings += count_crossings(edges[first], edges[second])
    report["crossings"] = crossings
    if crossings > max_crossings:
        problems.append({"kind": "edge-crossings", "count": crossings, "budget": max_crossings})

    fan_in: Dict[str, int] = {}
    for alias_a, alias_b, _ in edge_pairs:
        if alias_b:
            fan_in[alias_b] = fan_in.get(alias_b, 0) + 1
    report["fan_in"] = fan_in
    for alias, count in sorted(fan_in.items(), key=lambda item: -item[1]):
        if count > max_fan_in:
            problems.append({"kind": "fan-in", "element": alias, "arrows": count, "budget": max_fan_in})

    report["arrows"] = len(edges)
    report["labels"] = len(label_boxes)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help=".mmd sources (or directories) to check")
    parser.add_argument("--svg-dir", default=None, help="directory holding the renders (default: sibling svg/)")
    parser.add_argument("--max-crossings", type=int, default=MAX_CROSSINGS, help="allowed arrow crossings (default 2)")
    parser.add_argument("--max-fan-in", type=int, default=MAX_FAN_IN, help="allowed arrows into one element (default 3)")
    parser.add_argument(
        "--max-label-distance",
        type=float,
        default=MAX_LABEL_DISTANCE,
        help="how far a label may sit from its own arrow, in px (default 30)",
    )
    parser.add_argument(
        "--ambiguity-margin",
        type=float,
        default=AMBIGUITY_MARGIN,
        help="a label this close to a foreign arrow is ambiguous, in px (default 8)",
    )
    parser.add_argument(
        "--overlap-tolerance",
        type=float,
        default=OVERLAP_TOLERANCE,
        help="two arrows this close count as drawn on top of each other, in px (default 2.5)",
    )
    parser.add_argument(
        "--max-overlap",
        type=float,
        default=MAX_OVERLAP_LENGTH,
        help="how much shared path two arrows may have, in px (default 16)",
    )
    parser.add_argument(
        "--parallel-distance",
        type=float,
        default=PARALLEL_DISTANCE,
        help="two arrows this close count as a bundle, in px (default 8)",
    )
    parser.add_argument(
        "--max-parallel",
        type=float,
        default=MAX_PARALLEL_LENGTH,
        help="how long two arrows may stay bundled, in px (default 60)",
    )
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    args = parser.parse_args(argv)

    try:
        CL.load_font()
    except ImportError:
        print(
            "mermaidx is not installed: run python3 -m pip install mermaidx -i https://pypi.org/simple",
            file=sys.stderr,
        )
        return 1

    targets: List[Path] = []
    for raw in args.paths:
        path = Path(raw)
        targets.extend(sorted(path.rglob("*.mmd")) if path.is_dir() else [path])

    reports = []
    failures = 0
    for mmd in targets:
        if args.svg_dir:
            svg = Path(args.svg_dir) / (mmd.stem + ".svg")
        else:
            svg = mmd.parent.parent / "svg" / (mmd.stem + ".svg")
        if not svg.is_file():
            print("{}: ERROR: render not found at {}".format(mmd, svg))
            failures += 1
            continue
        report = check_diagram(
            mmd,
            svg,
            args.max_crossings,
            args.max_fan_in,
            args.max_label_distance,
            args.ambiguity_margin,
            args.overlap_tolerance,
            args.max_overlap,
            args.parallel_distance,
            args.max_parallel,
        )
        problems = report["problems"]
        errors = [problem for problem in problems if problem.get("level") != "warning"]
        failures += len(errors)
        reports.append(report)
        if not args.json:
            detail = report.get("note") or "{} arrow(s), {} label(s), {} crossing(s)".format(
                report.get("arrows", 0), report.get("labels", 0), report.get("crossings", 0)
            )
            print("{}: {} problem(s), {}".format(mmd, len(problems), detail))
            for problem in problems:
                if problem["kind"] == "label-foreign":
                    print(
                        "  LABEL-FOREIGN {!r}: {:.0f}px to own arrow, {:.0f}px to another arrow".format(
                            problem["text"], problem["distance_to_own_arrow"], problem["distance_to_other_arrow"]
                        )
                    )
                elif problem["kind"] == "label-ambiguous":
                    print(
                        "  LABEL-AMBIGUOUS {!r}: own {:.0f}px vs other {:.0f}px".format(
                            problem["text"], problem["distance_to_own_arrow"], problem["distance_to_other_arrow"]
                        )
                    )
                elif problem["kind"] == "label-crossed-by-arrow":
                    print(
                        "  LABEL-CROSSED-BY-ARROW {!r}: another arrow runs {:.0f}px through the label".format(
                            problem["text"], problem["penetration"]
                        )
                    )
                elif problem["kind"] == "label-on-arrow":
                    print(
                        "  LABEL-ON-ARROW {!r}: its own arrow runs {:.0f}px through the text".format(
                            problem["text"], problem["penetration"]
                        )
                    )
                elif problem["kind"] == "label-detached":
                    print(
                        "  LABEL-DETACHED {!r}: {:.0f}px from its own arrow".format(
                            problem["text"], problem["distance_to_own_arrow"]
                        )
                    )
                elif problem["kind"] == "edge-overlap":
                    print(
                        "  EDGE-OVERLAP {} and {} share {:.0f}px of drawn path (within {:.0f}px for {:.0f}px)".format(
                            problem["arrows"][0],
                            problem["arrows"][1],
                            problem["overlap_px"],
                            args.overlap_tolerance,
                            problem["bundle_px"],
                        )
                    )
                elif problem["kind"] == "edge-bundle":
                    print(
                        "  EDGE-BUNDLE {} and {} run {:.0f}px closer than {:.0f}px".format(
                            problem["arrows"][0], problem["arrows"][1], problem["parallel_px"], args.parallel_distance
                        )
                    )
                elif problem["kind"] == "shared-arrowhead":
                    print(
                        "  SHARED-ARROWHEAD {} and {} end on the same point ({} px apart)".format(
                            problem["arrows"][0], problem["arrows"][1], problem["parallel_px"]
                        )
                    )
                elif problem["kind"] == "edge-through-box":
                    print(
                        "  EDGE-THROUGH-BOX {}: {:.0f}px hidden under '{}'".format(
                            problem["arrows"], problem["hidden_px"], problem["element"]
                        )
                    )
                elif problem["kind"] == "edge-crossings":
                    print("  EDGE-CROSSINGS: {} crossings, budget {}".format(problem["count"], problem["budget"]))
                elif problem["kind"] == "fan-in":
                    print(
                        "  FAN-IN: {} arrows meet '{}', budget {}".format(
                            problem["arrows"], problem["element"], problem["budget"]
                        )
                    )
                else:
                    print("  {}: {}".format(problem["kind"].upper(), problem))

    if args.json:
        print(json.dumps({"reports": reports, "failures": failures}, indent=2))
    else:
        print("checked {} file(s): {} blocking problem(s)".format(len(targets), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
