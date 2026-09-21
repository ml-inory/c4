#!/usr/bin/env python3
"""Check rendered Mermaid SVGs for overlapping, clipped, or overflowing text.

Usage:
    python3 check_layout.py docs/c4/svg/*.svg [--json] [--tolerance 2]

Mermaid's C4 layout places relationship labels on the edge path, so labels can
land on top of element boxes, collide with other labels, or run past the canvas.
Widths are measured with the same bundled font metrics (DejaVu Sans) that
mermaidx uses for layout and rasterization, so the reported boxes match what the
PNG actually shows.

Exit code is 1 when any problem is found, otherwise 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

NS = "{http://www.w3.org/2000/svg}"


def load_font():
    from mermaidx.font_metrics import get_font

    return get_font()


def style_value(node, key: str) -> Optional[str]:
    match = re.search(r"{}\s*:\s*([^;]+)".format(key), node.get("style") or "")
    return match.group(1).strip() if match else None


def number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    match = re.match(r"\s*(-?[\d.]+)", raw)
    return float(match.group(1)) if match else None


def parse_translate(node) -> Tuple[float, float]:
    dx = dy = 0.0
    for part in re.findall(r"translate\(([^)]*)\)", node.get("transform") or ""):
        values = [number(v) for v in re.split(r"[,\s]+", part.strip()) if v.strip()]
        if values:
            dx += values[0] or 0.0
            dy += values[1] if len(values) > 1 else 0.0
    return dx, dy


class Run:
    def __init__(self, text: str, x0: float, x1: float, baseline: float, size: float) -> None:
        self.text = text
        self.x0 = x0
        self.x1 = x1
        self.baseline = baseline
        self.y0 = baseline - size * 0.8
        self.y1 = baseline + size * 0.25
        self.size = size

    def as_dict(self) -> Dict[str, object]:
        return {
            "text": self.text[:80],
            "x0": round(self.x0, 1),
            "x1": round(self.x1, 1),
            "y0": round(self.y0, 1),
            "y1": round(self.y1, 1),
        }


def text_runs(node, font, ox: float, oy: float, size: float, anchor: str, out: List[Run]) -> None:
    """Collect text runs, without descending into child groups."""
    dx, dy = parse_translate(node)
    ox, oy = ox + dx, oy + dy
    size = number(style_value(node, "font-size")) or number(node.get("font-size")) or size
    anchor = style_value(node, "text-anchor") or node.get("text-anchor") or anchor
    tag = node.tag.replace(NS, "")
    if tag in ("text", "tspan"):
        x = number(node.get("x"))
        y = number(node.get("y"))
        content = "".join(node.itertext()).strip()
        if content and x is not None and y is not None:
            width = number(node.get("textLength"))
            if width is None:
                units = sum(font.advance_width_units(ch) for ch in content)
                width = units / font.units_per_em * size
            x0 = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
            out.append(Run(content, ox + x0, ox + x0 + width, oy + y, size))
    for child in node:
        if child.tag.replace(NS, "") != "g":
            text_runs(child, font, ox, oy, size, anchor, out)


class Checker:
    def __init__(self, font, tolerance: float) -> None:
        self.font = font
        self.tolerance = tolerance
        self.problems: List[Dict[str, object]] = []

    def add(self, kind: str, run: Run, detail: Dict[str, object]) -> None:
        self.problems.append({"kind": kind, "text": run.text[:80], "run": run.as_dict(), **detail})

    def check_pair(self, first: Run, second: Run) -> None:
        ix = min(first.x1, second.x1) - max(first.x0, second.x0)
        iy = min(first.y1, second.y1) - max(first.y0, second.y0)
        if ix > self.tolerance and iy > self.tolerance:
            self.problems.append(
                {
                    "kind": "text_overlap",
                    "text": first.text[:80],
                    "other": second.text[:80],
                    "overlap_x": round(ix, 1),
                    "overlap_y": round(iy, 1),
                    "run": first.as_dict(),
                    "other_run": second.as_dict(),
                }
            )

    def check_box(self, run: Run, box: Tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = box
        if not (y0 - self.tolerance <= run.baseline <= y1 + self.tolerance):
            return
        left = max(x0 - run.x0, 0.0)
        right = max(run.x1 - x1, 0.0)
        if left > self.tolerance or right > self.tolerance:
            self.add(
                "box_overflow",
                run,
                {
                    "overflow_left": round(left, 1),
                    "overflow_right": round(right, 1),
                    "box": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                },
            )

    def walk_group(self, group, ox: float, oy: float) -> None:
        dx, dy = parse_translate(group)
        ox, oy = ox + dx, oy + dy
        boxes: List[Tuple[float, float, float, float]] = []
        runs: List[Run] = []
        for child in group:
            tag = child.tag.replace(NS, "")
            if tag == "g":
                continue
            if tag == "rect":
                cx, cy = parse_translate(child)
                x = number(child.get("x")) or 0.0
                y = number(child.get("y")) or 0.0
                width = number(child.get("width")) or 0.0
                height = number(child.get("height")) or 0.0
                if width > 80 and height > 30:
                    boxes.append((ox + cx + x, oy + cy + y, ox + cx + x + width, oy + cy + y + height))
            else:
                text_runs(child, self.font, ox, oy, 16.0, "start", runs)
        for run in runs:
            for box in boxes:
                self.check_box(run, box)
        for child in group:
            if child.tag.replace(NS, "") == "g":
                self.walk_group(child, ox, oy)

    def run_svg(self, svg_text: str, label: str = "<svg>") -> Dict[str, object]:
        root = ET.fromstring(svg_text)
        viewbox = [number(v) for v in (root.get("viewBox") or "").split()]
        self.walk_group(root, 0.0, 0.0)

        runs: List[Run] = []
        for child in root:
            if child.tag.replace(NS, "") == "g":
                self.collect_all(child, 0.0, 0.0, runs)
        unique: Dict[Tuple[str, float, float], Run] = {}
        for run in runs:
            unique[(run.text, round(run.x0, 1), round(run.baseline, 1))] = run
        runs = list(unique.values())
        for index, first in enumerate(runs):
            for second in runs[index + 1:]:
                self.check_pair(first, second)

        if len(viewbox) == 4:
            vx0, vy0 = viewbox[0], viewbox[1]
            vx1, vy1 = vx0 + viewbox[2], vy0 + viewbox[3]
            for run in runs:
                if (
                    run.x0 < vx0 - self.tolerance
                    or run.x1 > vx1 + self.tolerance
                    or run.y0 < vy0 - self.tolerance
                    or run.y1 > vy1 + self.tolerance
                ):
                    self.add("clipped", run, {"viewbox": [vx0, vy0, vx1, vy1]})
        return {"file": label, "text_runs": len(runs)}

    def run_document(self, path: Path) -> Dict[str, object]:
        return self.run_svg(path.read_text(encoding="utf-8"), label=str(path))

    def collect_all(self, node, ox: float, oy: float, out: List[Run]) -> None:
        dx, dy = parse_translate(node)
        ox, oy = ox + dx, oy + dy
        runs: List[Run] = []
        text_runs(node, self.font, ox, oy, 16.0, "start", runs)
        out.extend(runs)
        for child in node:
            if child.tag.replace(NS, "") == "g":
                self.collect_all(child, ox, oy, out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="rendered .svg files (or directories)")
    parser.add_argument("--tolerance", type=float, default=2.0, help="allowed overlap in px (default 2)")
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    args = parser.parse_args(argv)

    try:
        font = load_font()
    except ImportError:
        print(
            "mermaidx is not installed: run python3 -m pip install mermaidx -i https://pypi.org/simple",
            file=sys.stderr,
        )
        return 1

    targets: List[Path] = []
    for raw in args.paths:
        path = Path(raw)
        targets.extend(sorted(path.rglob("*.svg")) if path.is_dir() else [path])

    reports = []
    failures = 0
    for path in targets:
        if not path.is_file():
            print("{}: ERROR: file not found".format(path))
            failures += 1
            continue
        checker = Checker(font, args.tolerance)
        summary = checker.run_document(path)
        summary["problems"] = checker.problems
        reports.append(summary)
        failures += len(checker.problems)
        if not args.json:
            print("{}: {} problem(s), {} text runs".format(path, len(checker.problems), summary["text_runs"]))
            for problem in checker.problems:
                if problem["kind"] == "text_overlap":
                    print(
                        "  TEXT-OVERLAP {:.0f}x{:.0f}px: {!r} vs {!r}".format(
                            problem["overlap_x"], problem["overlap_y"], problem["text"], problem["other"]
                        )
                    )
                elif problem["kind"] == "box_overflow":
                    print(
                        "  BOX-OVERFLOW left={:.0f}px right={:.0f}px: {!r}".format(
                            problem["overflow_left"], problem["overflow_right"], problem["text"]
                        )
                    )
                else:
                    print("  CLIPPED: {!r} at {}".format(problem["text"], problem["run"]))

    if args.json:
        print(json.dumps({"reports": reports, "problems": failures}, indent=2))
    else:
        print("checked {} file(s): {} problem(s)".format(len(targets), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
