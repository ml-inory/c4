#!/usr/bin/env python3
"""Move relationship labels out of the element boxes they collide with.

Usage:
    python3 fit_labels.py docs/c4/diagrams/*.mmd [--apply] [--config assets/mermaid-config.json]

Mermaid's C4 layout puts each relationship label on the edge path, so labels
regularly land on top of element boxes. Widening `c4ShapeMargin` (see
assets/mermaid-config.json) removes most collisions; this tool resolves what is
left by adding `UpdateRelStyle(... $offsetX/$offsetY)` nudges, which shift only
the label, never the layout.

Without `--apply` it prints what it would change. With `--apply` it rewrites the
.mmd files and re-renders until every label is clear of the boxes (or the
iteration budget is exhausted).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import check_layout as CL

NS = "{http://www.w3.org/2000/svg}"
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "assets" / "mermaid-config.json"
MARGIN = 6.0
MAX_SHIFT = 160.0
# Total displacement budget per label: a label that has to travel further than this
# is no longer visually attached to its own connector line.
MAX_TOTAL_SHIFT = 120.0
# Labels must keep clear of every obstacle, not merely avoid overlapping it:
# "touching the border" and "abutting a description" read as defects too.
CLEARANCE = 6.0


def load_config(path: Path) -> Dict[str, object]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def parse_relations(source: str) -> List[List[object]]:
    """Return [aliasA, aliasB, label, technology, (offsetX, offsetY) or None]."""
    relations: List[List[object]] = []
    pattern = re.compile(
        r'^\s*(?:Rel\w*|BiRel\w*)\(\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?',
        re.M,
    )
    for match in pattern.finditer(source):
        relations.append([match.group(1), match.group(2), match.group(3), match.group(4) or "", None])
    for match in re.finditer(
        r'^\s*UpdateRelStyle\(\s*(\w+)\s*,\s*(\w+)\s*,\s*\$offsetX="(-?[\d.]+)"\s*,\s*\$offsetY="(-?[\d.]+)"',
        source,
        re.M,
    ):
        for relation in relations:
            if relation[0] == match.group(1) and relation[1] == match.group(2):
                relation[4] = (float(match.group(3)), float(match.group(4)))
    return relations


def geometry(svg_text: str, font):
    root = ET.fromstring(svg_text)
    viewbox = [float(v) for v in (root.get("viewBox") or "").split()]
    boxes = []
    for node in root.iter(NS + "rect"):
        width = CL.number(node.get("width")) or 0
        height = CL.number(node.get("height")) or 0
        fill = (node.get("fill") or "").upper()
        if width > 80 and height > 30 and fill not in ("", "NONE", "#FFFFFF", "WHITE"):
            x, y = CL.number(node.get("x")) or 0, CL.number(node.get("y")) or 0
            boxes.append((x, y, x + width, y + height))
    runs = []
    for child in root:
        if child.tag.replace(NS, "") == "g":
            CL.Checker(font, 0).collect_all(child, 0.0, 0.0, runs)
    unique = {(run.text, round(run.x0, 1), round(run.baseline, 1)): run for run in runs}
    return viewbox, boxes, list(unique.values())


def label_boxes(relations, runs):
    """Return label bboxes per relationship plus the ids of runs used as labels."""
    by_text: Dict[str, List] = {}
    for run in runs:
        by_text.setdefault(run.text, []).append(run)
        # C4Dynamic prefixes relationship labels with their step number ("3: ...").
        stripped = re.sub(r"^\d+:\s*", "", run.text)
        if stripped != run.text:
            by_text.setdefault(stripped, []).append(run)
    result = {}
    used = set()
    for alias_a, alias_b, label, tech, _ in relations:
        anchors = [run for run in by_text.get(label, []) if run.baseline > 0]
        if not anchors:
            continue
        anchor = max(anchors, key=lambda run: run.baseline)
        parts = [anchor]
        if tech:
            parts.extend(
                run
                for run in by_text.get("[{}]".format(tech), [])
                if abs(run.baseline - anchor.baseline) < 30
            )
        used.update(id(part) for part in parts)
        result[(str(alias_a), str(alias_b))] = (
            min(part.x0 for part in parts),
            min(part.y0 for part in parts),
            max(part.x1 for part in parts),
            max(part.y1 for part in parts),
        )
    return result, used


def penalty(box, boxes, others, viewbox) -> float:
    x0, y0, x1, y1 = box
    total = 0.0
    for bx0, by0, bx1, by1 in boxes:
        ix = min(x1, bx1 + CLEARANCE) - max(x0, bx0 - CLEARANCE)
        iy = min(y1, by1 + CLEARANCE) - max(y0, by0 - CLEARANCE)
        if ix > 0 and iy > 0:
            total += (ix + iy) * 3
    for ox0, oy0, ox1, oy1 in others.values():
        ix = min(x1, ox1) - max(x0, ox0)
        iy = min(y1, oy1) - max(y0, oy0)
        if ix > 2 and iy > 2:
            total += ix + iy
    vx0, vy0, vx1, vy1 = viewbox
    for value, low, high in ((x0, vx0, vx1), (x1, vx0, vx1), (y0, vy0, vy1), (y1, vy0, vy1)):
        if value < low:
            total += (low - value) * 4
        elif value > high:
            total += (value - high) * 4
    return total


def proximity(box, anchor, weight: float = 0.6) -> float:
    """Distance from the label's natural position: labels must stay near their line."""
    dy = abs(box[1] - anchor[1])
    dx = abs((box[0] + box[2]) / 2 - (anchor[0] + anchor[2]) / 2)
    return (dy + 0.25 * dx) * weight


def inside(box, viewbox) -> bool:
    x0, y0, x1, y1 = box
    vx0, vy0, vx1, vy1 = viewbox
    return x0 >= vx0 and x1 <= vx1 and y0 >= vy0 and y1 <= vy1


def total_penalty(labels, obstacles, viewbox, skip=None) -> float:
    return sum(
        penalty(box, obstacles, {k: v for k, v in labels.items() if k != key}, viewbox)
        for key, box in labels.items()
        if key != skip
    )


def solve(relations, boxes, labels, viewbox, anchors=None, step: float = 20.0):
    """Bounded search: move each label to the best in-canvas position."""
    offsets: Dict[Tuple[str, str], List[float]] = {}
    for alias_a, alias_b, _, _, existing in relations:
        offsets[(str(alias_a), str(alias_b))] = list(existing) if existing else [0.0, 0.0]
    current = dict(labels)
    anchors = anchors or dict(labels)
    for _ in range(6):
        improved = False
        order = sorted(
            current,
            key=lambda key: -(
                penalty(current[key], boxes, {k: v for k, v in current.items() if k != key}, viewbox)
                + proximity(current[key], anchors[key])
            ),
        )
        for key in order:
            others = {k: v for k, v in current.items() if k != key}
            base = penalty(current[key], boxes, others, viewbox) + proximity(current[key], anchors[key])
            if base <= 0:
                continue
            x0, y0, x1, y1 = current[key]
            best = None
            for shift_x in range(int(-MAX_SHIFT), int(MAX_SHIFT) + 1, int(step)):
                for shift_y in range(int(-MAX_SHIFT), int(MAX_SHIFT) + 1, int(step)):
                    candidate = (x0 + shift_x, y0 + shift_y, x1 + shift_x, y1 + shift_y)
                    if not inside(candidate, viewbox):
                        continue
                    total_x = offsets[key][0] + shift_x
                    total_y = offsets[key][1] + shift_y
                    if abs(total_x) > MAX_TOTAL_SHIFT or abs(total_y) > MAX_TOTAL_SHIFT:
                        continue
                    value = penalty(candidate, boxes, others, viewbox) + proximity(candidate, anchors[key])
                    if best is None or value < best[0]:
                        best = (value, (shift_x, shift_y), candidate)
            # Only accept a move that removes the collision, not one that merely
            # trades it for a smaller one: labels must not drift away from their line.
            if best is not None and best[0] < base and penalty(best[2], boxes, others, viewbox) <= 0:
                offsets[key][0] += best[1][0]
                offsets[key][1] += best[1][1]
                current[key] = best[2]
                improved = True
        if not improved:
            break
    return offsets


def rewrite(source: str, offsets) -> str:
    source = re.sub(r'^\s*UpdateRelStyle\([^\n]*\$offsetX[^\n]*\)\s*\n', '', source, flags=re.M)
    lines = [
        '    UpdateRelStyle({}, {}, $offsetX="{:.0f}", $offsetY="{:.0f}")'.format(a, b, dx, dy)
        for (a, b), (dx, dy) in offsets.items()
        if abs(dx) >= 0.5 or abs(dy) >= 0.5
    ]
    if not lines:
        return source
    return source.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def process(path: Path, mermaidx, config, font, apply: bool) -> int:
    source = path.read_text(encoding="utf-8")
    for attempt in range(8):
        diagram = mermaidx.render(source, config=config) if config else mermaidx.render(source)
        viewbox, boxes, runs = geometry(diagram.svg(), font)
        relations = parse_relations(source)
        labels, label_run_ids = label_boxes(relations, runs)
        if not labels:
            print("{}: no relationship labels found".format(path))
            return 0
        # Element and boundary text is an obstacle too: labels must stay clear of it
        # even when they sit in the gaps between boxes.
        text_obstacles = [
            (run.x0, run.y0, run.x1, run.y1) for run in runs if id(run) not in label_run_ids
        ]
        anchors = dict(labels)
        obstacles = boxes + text_obstacles
        dirty = {
            key: penalty(box, obstacles, {k: v for k, v in labels.items() if k != key}, viewbox)
            for key, box in labels.items()
        }
        dirty = {k: v for k, v in dirty.items() if v > 0}
        if not dirty:
            # Re-check with the full layout checker so clipping and box overflow are
            # covered too, not just label collisions.
            checker = CL.Checker(font, 2.0)
            checker.run_svg(diagram.svg(), label=str(path))
            if checker.problems:
                kinds = sorted({problem["kind"] for problem in checker.problems})
                print(
                    "{}: labels clear but {} layout problem(s) remain: {}".format(
                        path, len(checker.problems), ", ".join(kinds)
                    )
                )
                if apply:
                    path.write_text(source, encoding="utf-8")
                return 1
            print("{}: all {} label(s) clear after {} render(s)".format(path, len(labels), attempt + 1))
            if apply:
                path.write_text(source, encoding="utf-8")
            return 0
        offsets = solve(relations, obstacles, labels, viewbox, anchors=anchors)
        updated = rewrite(source, offsets)
        if updated == source:
            print("{}: {} label(s) still colliding, needs manual offsets: {}".format(path, len(dirty), sorted(dirty)))
            if apply:
                path.write_text(source, encoding="utf-8")
            return 1
        source = updated
    print("{}: still colliding after 8 rounds".format(path))
    if apply:
        path.write_text(source, encoding="utf-8")
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="Mermaid .mmd files to inspect or fix")
    parser.add_argument("--apply", action="store_true", help="rewrite the files (default: dry run)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="mermaid config JSON")
    args = parser.parse_args(argv)

    try:
        import mermaidx
    except ImportError:
        print("mermaidx is not installed: python3 -m pip install mermaidx -i https://pypi.org/simple", file=sys.stderr)
        return 1

    config = load_config(Path(args.config))
    font = CL.load_font()
    failures = 0
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*.mmd")):
                failures += process(child, mermaidx, config, font, args.apply)
        else:
            failures += process(path, mermaidx, config, font, args.apply)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
