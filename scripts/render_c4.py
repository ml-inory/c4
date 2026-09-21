#!/usr/bin/env python3
"""Render Mermaid C4 sources to PNG and SVG with mermaidx, updating a manifest.

Usage:
    python3 render_c4.py --src docs/c4/diagrams [--png docs/c4/png] [--svg docs/c4/svg]

Defaults are derived from the source directory: ../png, ../svg, and
../manifest.json. mermaidx is installed on demand from PyPI because some
mirror indexes do not carry the package.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

FALLBACK_INDEX = "https://pypi.org/simple"
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "assets" / "mermaid-config.json"
DEFAULT_CSS = SKILL_ROOT / "assets" / "mermaid-halo.css"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
NS = "{{{}}}".format(SVG_NS)


def reorder_connectors(svg_text: str, measure=None, halo: bool = True) -> str:
    """Paint relationship lines behind the element boxes and labels in front.

    Mermaid emits one group holding both the connector paths and the relationship
    labels, and paints it after the node groups. With the C4 layout that leaves
    connector stubs and arrow heads drawn on top of element boxes and boundary
    text. Splitting the group fixes the layering without touching the diagram
    source: connectors first (hidden by the boxes they run into), labels last.
    """
    try:
        ET.register_namespace("", SVG_NS)
        ET.register_namespace("xlink", XLINK_NS)
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return svg_text

    connector_group = None
    label_group = None
    relationship_group = None
    for child in list(root):
        if child.tag != NS + "g":
            continue
        kinds = {element.tag.replace(NS, "") for element in child}
        if kinds & {"line", "path", "polyline"} and "text" in kinds:
            relationship_group = child
            connector_group = ET.Element(NS + "g", {"class": "connectors"})
            label_group = ET.Element(NS + "g", {"class": "relationship-labels"})
            for element in list(child):
                kind = element.tag.replace(NS, "")
                target = label_group if kind == "text" else connector_group
                child.remove(element)
                target.append(element)
            break
    if connector_group is None or label_group is None:
        return svg_text

    root.remove(relationship_group)
    root.insert(0, connector_group)
    root.append(label_group)

    if halo:
        # resvg ignores paint-order strokes on text, so masking is done with real
        # rectangles: a white plate is painted directly under every relationship
        # label and boundary caption, hiding the connector lines that would
        # otherwise run through them. Element boxes keep their coloured fill, so
        # their own text is left untouched.
        for element in list(label_group):
            plate = label_plate(element, measure)
            if plate is not None:
                label_group.insert(list(label_group).index(element), plate)
        for group in root:
            if group is label_group or group.tag != NS + "g":
                continue
            if not is_unfilled_group(group):
                continue
            for element in list(group):
                plate = label_plate(element, measure)
                if plate is not None:
                    group.insert(list(group).index(element), plate)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


def label_plate(element, measure=None) -> Optional[ET.Element]:
    """White background rectangle for one relationship label run."""
    if element.tag != NS + "text":
        return None
    content = "".join(element.itertext()).strip()
    x = element.get("x")
    y = element.get("y")
    if not content or x is None or y is None:
        return None
    size = 12.0
    match = re.search(r"font-size:\s*([\d.]+)", element.get("style") or "")
    if match:
        size = float(match.group(1))
    if measure is not None:
        width = measure(content, size)
    else:
        width = len(content) * size * 0.55
    anchor = "start"
    anchor_match = re.search(r"text-anchor:\s*(\w+)", element.get("style") or "")
    if anchor_match:
        anchor = anchor_match.group(1)
    center = float(x)
    if anchor == "middle":
        left = center - width / 2
    elif anchor == "end":
        left = center - width
    else:
        left = center
    baseline = float(y)
    plate = ET.Element(
        NS + "rect",
        {
            "x": "{:.1f}".format(left - 3),
            "y": "{:.1f}".format(baseline - size * 0.85),
            "width": "{:.1f}".format(width + 6),
            "height": "{:.1f}".format(size * 1.15),
            "fill": "#ffffff",
            "class": "label-plate",
        },
    )
    return plate


def is_unfilled_group(group) -> bool:
    """True for caption groups (boundaries) whose shapes are not filled boxes."""
    shapes = [
        element
        for element in group
        if element.tag in (NS + "rect", NS + "path", NS + "polygon", NS + "circle")
    ]
    if not shapes or not any(element.tag == NS + "text" for element in group):
        return False
    for shape in shapes:
        fill = (shape.get("fill") or "none").strip().lower()
        if fill not in ("none", "transparent", "#ffffff", "white"):
            return False
    return True


def log(message: str) -> None:
    print(message, flush=True)


def png_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG payload")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def ensure_mermaidx() -> object:
    """Import mermaidx, installing it from PyPI when it is missing."""
    try:
        import mermaidx

        return mermaidx
    except ImportError:
        log("mermaidx not found: installing from {}".format(FALLBACK_INDEX))

    command = [sys.executable, "-m", "pip", "install", "mermaidx", "-i", FALLBACK_INDEX]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
        log("pip install mermaidx failed:\n{}".format("\n".join(tail)))
        log("install manually with: {}".format(" ".join(command)))
        raise SystemExit(1)
    try:
        import mermaidx

        return mermaidx
    except ImportError:
        log("mermaidx still unavailable after install; run: {}".format(" ".join(command)))
        raise SystemExit(1)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> Dict[str, object]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            log("warning: {} is not valid JSON, rebuilding it".format(path))
    return {}


def relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_one(
    mermaidx: object,
    text: str,
    config: Dict[str, object],
    css: str,
    args: argparse.Namespace,
) -> Tuple[bytes, str, Tuple[int, int], float]:
    opts = {"theme": args.theme} if args.theme else {}
    if config:
        opts["config"] = config
    if css:
        opts["css"] = css
    diagram = mermaidx.render(text, backend=args.backend, **opts)
    def measure(content: str, size: float) -> float:
        try:
            font = mermaidx.font_metrics.get_font()
            units = sum(font.advance_width_units(ch) for ch in content)
            return units / font.units_per_em * size
        except Exception:
            return len(content) * size * 0.55

    svg = reorder_connectors(diagram.svg(), measure=measure)
    png_kwargs: Dict[str, object] = {"background": args.background}
    viewbox_width = 0.0
    if args.width or args.height:
        png_kwargs["width"] = args.width
        png_kwargs["height"] = args.height
    else:
        viewbox = re.search(r'viewBox="([-\d.\s]+)"', svg)
        if viewbox:
            values = [float(value) for value in viewbox.group(1).split()]
            viewbox_width = values[2]
            png_kwargs["width"] = values[2] * args.scale
        else:
            png_kwargs["scale"] = args.scale
    png = mermaidx.svg_to_png(svg, **png_kwargs)
    return png, svg, png_size(png), viewbox_width


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--src", required=True, help="directory containing .mmd sources")
    parser.add_argument("--png", help="PNG output directory (default: <src>/../png)")
    parser.add_argument("--svg", help="SVG output directory (default: <src>/../svg)")
    parser.add_argument("--manifest", help="manifest path (default: <src>/../manifest.json)")
    parser.add_argument("--scale", type=float, default=2.0, help="PNG size multiplier (default: 2.0)")
    parser.add_argument("--width", type=float, help="PNG width in pixels (disables --scale)")
    parser.add_argument("--height", type=float, help="PNG height in pixels (disables --scale)")
    parser.add_argument("--theme", default="default", help="Mermaid theme (default: default)")
    parser.add_argument("--background", default="#ffffff", help="PNG background (default: #ffffff)")
    parser.add_argument("--backend", default=None, help="mermaidx backend (default: quickjs)")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="mermaid config JSON with C4 layout settings (default: skill assets/mermaid-config.json)",
    )
    parser.add_argument("--no-config", action="store_true", help="ignore the default mermaid config")
    parser.add_argument(
        "--css",
        default=str(DEFAULT_CSS),
        help="CSS injected into the diagram (default: skill assets/mermaid-halo.css)",
    )
    parser.add_argument("--no-css", action="store_true", help="do not inject any CSS")
    parser.add_argument("--force", action="store_true", help="re-render unchanged sources")
    parser.add_argument("--check-only", action="store_true", help="render in memory, write nothing")
    args = parser.parse_args(argv)

    src_dir = Path(args.src)
    if not src_dir.is_dir():
        log("source directory not found: {}".format(src_dir))
        return 1

    sources = sorted(src_dir.rglob("*.mmd"))
    if not sources:
        log("no .mmd files found under {}".format(src_dir))
        return 1

    root = src_dir.parent
    png_dir = Path(args.png) if args.png else root / "png"
    svg_dir = Path(args.svg) if args.svg else root / "svg"
    manifest_path = Path(args.manifest) if args.manifest else root / "manifest.json"

    manifest = load_manifest(manifest_path)
    previous: Dict[str, Dict[str, object]] = {}
    for entry in manifest.get("diagrams", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("source"), str):
            previous[entry["source"]] = entry

    if not args.check_only:
        png_dir.mkdir(parents=True, exist_ok=True)
        svg_dir.mkdir(parents=True, exist_ok=True)

    mermaidx = ensure_mermaidx()
    version = getattr(mermaidx, "__version__", "unknown")

    config: Dict[str, object] = {}
    config_label = "none"
    if not args.no_config:
        config_path = Path(args.config)
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config_label = "{} ({})".format(config_path.name, hashlib.sha256(config_path.read_bytes()).hexdigest()[:8])
        else:
            log("warning: config {} not found, rendering with mermaid defaults".format(config_path))

    css = ""
    css_label = "none"
    if not args.no_css:
        css_path = Path(args.css)
        if css_path.is_file():
            css = css_path.read_text(encoding="utf-8")
            css_label = "{} ({})".format(css_path.name, hashlib.sha256(css.encode()).hexdigest()[:8])
        else:
            log("warning: css {} not found, rendering without it".format(css_path))
    log(
        "mermaidx {} | backend {} | scale {} | config {} | css {}{}".format(
            version,
            args.backend or "quickjs",
            args.scale,
            config_label,
            css_label,
            " | check-only" if args.check_only else "",
        )
    )

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    render_options = {
        "scale": args.scale,
        "width": args.width,
        "height": args.height,
        "theme": args.theme,
        "background": args.background,
        "backend": args.backend or "quickjs",
        "config": config_label,
        "css": css_label,
    }
    entries: List[Dict[str, object]] = []
    failures = 0

    for source in sources:
        text = source.read_text(encoding="utf-8")
        digest = sha256(text)
        key = relative_to(source, root)
        png_path = png_dir / (source.stem + ".png")
        svg_path = svg_dir / (source.stem + ".svg")
        cached = previous.get(key)
        unchanged = (
            not args.force
            and not args.check_only
            and cached is not None
            and cached.get("source_sha256") == digest
            and cached.get("render") == render_options
            and png_path.is_file()
            and svg_path.is_file()
        )
        if unchanged:
            log(
                "SKIP  {} (unchanged) {}x{}".format(
                    png_path, cached.get("width"), cached.get("height")
                )
            )
            entries.append(dict(cached))
            continue

        try:
            png, svg, (width, height), viewbox_width = render_one(mermaidx, text, config, css, args)
        except Exception as exc:  # surface renderer failures verbatim
            failures += 1
            log("FAIL  {}: {}".format(source, str(exc).splitlines()[0][:200]))
            entries.append(
                {
                    "name": source.stem,
                    "source": key,
                    "source_sha256": digest,
                    "png": relative_to(png_path, manifest_path.parent),
                    "svg": relative_to(svg_path, manifest_path.parent),
                    "width": None,
                    "height": None,
                    "status": "failed",
                    "render": render_options,
                    "rendered_at": now,
                }
            )
            continue

        if not args.check_only:
            png_path.write_bytes(png)
            svg_path.write_text(svg, encoding="utf-8")
        entries.append(
            {
                "name": source.stem,
                "source": key,
                "source_sha256": digest,
                "png": relative_to(png_path, manifest_path.parent),
                "svg": relative_to(svg_path, manifest_path.parent),
                "width": width,
                "height": height,
                "status": "checked" if args.check_only else "rendered",
                "render": render_options,
                "rendered_at": now,
            }
        )
        log(
            "{}  {} {}x{}".format(
                "CHECK" if args.check_only else "OK   ",
                source if args.check_only else png_path,
                width,
                height,
            )
        )
        effective_scale = width / viewbox_width if viewbox_width else args.scale
        if effective_scale < 1.5:
            log(
                "      warning: {} renders at {:.2f} image pixels per diagram pixel, so "
                "label text will be small when the image is scaled to fit; raise "
                "--scale (2.0 is a good default)".format(source.stem, effective_scale)
            )
        if width > 6000:
            log("      warning: {} is {}px wide; consider --scale 1.5".format(source.stem, width))

    if not args.check_only:
        manifest = {
            "generated_by": "c4 skill scripts/render_c4.py",
            "mermaidx_version": version,
            "backend": args.backend or "quickjs",
            "scale": args.scale,
            "background": args.background,
            "theme": args.theme,
            "config": config_label,
            "css": css_label,
            "updated_at": now,
            "diagrams": sorted(entries, key=lambda item: str(item.get("source"))),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        log("manifest: {}".format(manifest_path))

    if failures:
        log("{} diagram(s) failed".format(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
