#!/usr/bin/env python3
"""Validate Mermaid C4 diagram sources before rendering.

Usage:
    python3 validate_c4.py docs/c4/diagrams [--no-render] [--json]

Checks native Mermaid C4 syntax (C4Context, C4Container, C4Component,
C4Dynamic, C4Deployment) for structural defects and known renderer failure
modes, then optionally smoke-renders each diagram to a PNG.

Exit code is 1 when any error is reported, otherwise 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

NATIVE_HEADERS = {"C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment"}
FALLBACK_HEADERS = {
    "flowchart",
    "graph",
    "classDiagram",
    "sequenceDiagram",
    "stateDiagram",
    "stateDiagram-v2",
}

ELEMENT_TYPES = {
    "Person",
    "Person_Ext",
    "System",
    "System_Ext",
    "SystemDb",
    "SystemDb_Ext",
    "SystemQueue",
    "SystemQueue_Ext",
    "Container",
    "Container_Ext",
    "ContainerDb",
    "ContainerDb_Ext",
    "ContainerQueue",
    "ContainerQueue_Ext",
    "Component",
    "Component_Ext",
    "ComponentDb",
    "ComponentDb_Ext",
    "ComponentQueue",
    "ComponentQueue_Ext",
    "Deployment_Node",
    "Node",
    "Node_L",
    "Node_R",
}

BOUNDARY_TYPES = {"Boundary", "Enterprise_Boundary", "System_Boundary", "Container_Boundary"}
REL_RE = re.compile(r"^(?:Bi)?Rel(_[A-Za-z]+)?$")
DIRECTIVES = {"UpdateElementStyle", "UpdateRelStyle", "UpdateLayoutConfig"}

# Element types whose declaration must carry a technology and a description.
TECH_TYPES = {
    "Container",
    "Container_Ext",
    "ContainerDb",
    "ContainerDb_Ext",
    "ContainerQueue",
    "ContainerQueue_Ext",
    "Component",
    "Component_Ext",
    "ComponentDb",
    "ComponentDb_Ext",
    "ComponentQueue",
    "ComponentQueue_Ext",
    "Deployment_Node",
}

ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9A-Fa-f]+);")
CALL_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<args>.*)$")
TITLE_RE = re.compile(r"^\s*title\s*(?P<text>.*)$")
TITLE_COMMENT_RE = re.compile(r"^\s*%%\s*title\s*:\s*(?P<text>.+?)\s*$")
FRONT_MATTER_TITLE_RE = re.compile(r"^\s*title\s*:\s*(?P<text>.+?)\s*$")
ALLOW_ORPHAN_RE = re.compile(r"^\s*%%\s*allow-orphan\s*:\s*(?P<aliases>.+?)\s*$")
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "assets" / "mermaid-config.json"


class Issue:
    def __init__(self, path: Path, line: int, severity: str, message: str) -> None:
        self.path = path
        self.line = line
        self.severity = severity
        self.message = message

    def as_dict(self) -> Dict[str, object]:
        return {
            "path": str(self.path),
            "line": self.line,
            "severity": self.severity,
            "message": self.message,
        }


def strip_comment(line: str) -> str:
    """Remove a trailing %% comment, ignoring %% inside quoted strings."""
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string and line.startswith("%%", i):
            return line[:i]
        i += 1
    return line


def split_args(text: str) -> List[str]:
    """Split a call argument list on top-level commas."""
    args: List[str] = []
    current: List[str] = []
    in_string = False
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            current.append(ch)
            if i + 1 < len(text):
                current.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    return text


def brace_delta(text: str) -> int:
    """Net open minus close braces, ignoring braces inside quoted strings."""
    in_string = False
    delta = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                delta += 1
            elif ch == "}":
                delta -= 1
        i += 1
    return delta


def png_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG payload")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class Validator:
    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.lines = text.splitlines()
        self.issues: List[Issue] = []
        self.elements: Dict[str, Dict[str, object]] = {}
        self.boundaries: Dict[str, int] = {}
        self.relations: List[Tuple[str, str, int]] = []
        self.header: Optional[str] = None
        self.uses_native_c4 = False
        self.allowed_orphans = set()

    def add(self, line: int, severity: str, message: str) -> None:
        self.issues.append(Issue(self.path, line, severity, message))

    def scan_ascii(self) -> None:
        for number, raw in enumerate(self.lines, start=1):
            allowed = ALLOW_ORPHAN_RE.match(raw)
            if allowed:
                self.allowed_orphans.update(
                    alias.strip() for alias in allowed.group("aliases").split(",") if alias.strip()
                )
            for ch in raw:
                if ord(ch) > 127:
                    self.add(
                        number,
                        "warning",
                        "non-ASCII character {!r}: mermaidx bundles DejaVu Sans only, "
                        "so non-Latin text renders as missing glyphs".format(ch),
                    )
                    break

    def scan_header(self) -> None:
        # A leading YAML front matter block (used for the rendered title of
        # fallback diagrams) is not the diagram header.
        in_front_matter = False
        for number, raw in enumerate(self.lines, start=1):
            stripped = strip_comment(raw).strip()
            if stripped == "---":
                in_front_matter = not in_front_matter
                continue
            if in_front_matter:
                continue
            if not stripped:
                continue
            token = re.split(r"[\s;]", stripped, maxsplit=1)[0]
            self.header = token
            if token in NATIVE_HEADERS:
                self.uses_native_c4 = True
                return
            if token in FALLBACK_HEADERS:
                self.add(
                    number,
                    "info",
                    "non-native C4 syntax '{}': deep C4 checks skipped, "
                    "C4-styled fallback rules applied".format(token),
                )
                return
            self.add(
                number,
                "error",
                "unsupported diagram header '{}': expected one of {}".format(
                    token, ", ".join(sorted(NATIVE_HEADERS))
                ),
            )
            return
        self.add(1, "error", "no diagram content found")

    def scan_native(self) -> None:
        depth = 0
        title_seen = False
        for number, raw in enumerate(self.lines, start=1):
            line = strip_comment(raw)
            stripped = line.strip()
            if not stripped or stripped == self.header:
                continue

            match = TITLE_RE.match(line)
            if match:
                title_seen = True
                title_text = match.group("text").strip()
                if not title_text:
                    self.add(number, "error", "empty title: give the diagram a name and scope")
                elif ENTITY_RE.search(title_text):
                    self.add(
                        number,
                        "error",
                        "HTML entity in the title line is a lexical error in Mermaid: "
                        "use a raw character or rephrase",
                    )
                continue

            call = CALL_RE.match(line)
            if not call:
                if stripped not in {"}", "};"}:
                    self.add(
                        number,
                        "warning",
                        "unrecognized statement: {!r}".format(stripped[:60]),
                    )
                depth += brace_delta(line)
                if depth > 3:
                    self.add(number, "error", "boundary nesting deeper than three levels")
                continue

            name = call.group("name")
            args = split_args(call.group("args"))
            depth += brace_delta(line)
            if depth > 3:
                self.add(number, "error", "boundary nesting deeper than three levels")
            if depth < 0:
                self.add(number, "error", "unbalanced closing brace")
                depth = 0

            if name in ELEMENT_TYPES:
                self.record_element(name, args, number)
            elif name in BOUNDARY_TYPES:
                self.record_boundary(name, args, number, line)
            elif REL_RE.match(name):
                self.record_relation(name, args, number)
            elif name in DIRECTIVES:
                self.check_directive(name, args, number)
            else:
                self.add(
                    number,
                    "warning",
                    "unrecognized statement '{}': not a C4 element, boundary, "
                    "relationship, or style directive".format(name),
                )

        if not title_seen:
            self.add(1, "error", "missing 'title' line: every C4 diagram needs a title")
        if depth != 0:
            self.add(len(self.lines), "error", "unbalanced braces: boundary block not closed")

    def record_element(self, kind: str, args: List[str], number: int) -> None:
        if not args:
            self.add(number, "error", "{} declaration without an alias".format(kind))
            return
        alias = unquote(args[0])
        if alias in self.elements or alias in self.boundaries:
            self.add(number, "error", "duplicate alias '{}'".format(alias))
            return
        label = unquote(args[1]) if len(args) > 1 else ""
        if not label:
            self.add(number, "warning", "element '{}' has no name".format(alias))
        if kind in TECH_TYPES:
            description = unquote(args[3]) if len(args) > 3 else ""
            expected = 4
        else:
            description = unquote(args[2]) if len(args) > 2 else ""
            expected = 3
        if len(args) < expected or not description:
            self.add(
                number,
                "warning",
                "element '{}' has no short description; the C4 checklist expects "
                "every element to be described".format(alias),
            )
        self.elements[alias] = {"kind": kind, "label": label, "line": number}

    def record_boundary(self, kind: str, args: List[str], number: int, line: str) -> None:
        if not args:
            self.add(number, "error", "{} declaration without an alias".format(kind))
            return
        alias = unquote(args[0])
        if alias in self.elements or alias in self.boundaries:
            self.add(number, "error", "duplicate alias '{}'".format(alias))
            return
        self.boundaries[alias] = number
        if "{" not in line:
            self.add(
                number,
                "warning",
                "boundary '{}' has no brace block; its children will not be grouped".format(alias),
            )

    def record_relation(self, kind: str, args: List[str], number: int) -> None:
        if len(args) < 2:
            self.add(number, "error", "{} declaration needs two element aliases".format(kind))
            return
        self.relations.append((unquote(args[0]), unquote(args[1]), number))

    def check_directive(self, name: str, args: List[str], number: int) -> None:
        if name == "UpdateLayoutConfig" or not args:
            return
        targets = [unquote(arg) for arg in args[:2]] if name == "UpdateRelStyle" else [unquote(args[0])]
        for target in targets:
            if target and target not in self.elements and target not in self.boundaries:
                self.add(
                    number,
                    "warning",
                    "{} references undeclared alias '{}'".format(name, target),
                )

    def validate_relations(self) -> None:
        connected = set()
        for source, target, number in self.relations:
            for endpoint in (source, target):
                if endpoint in self.boundaries:
                    self.add(
                        number,
                        "error",
                        "relationship targets boundary '{}': Mermaid C4 aborts with "
                        "'cannot read property x of undefined'. Point it at a concrete "
                        "element inside the boundary".format(endpoint),
                    )
                elif endpoint not in self.elements:
                    self.add(
                        number,
                        "error",
                        "relationship references undeclared alias '{}'".format(endpoint),
                    )
                else:
                    connected.add(endpoint)
        # Deployment nodes group other elements, so containment counts as connectivity.
        grouping = {"Deployment_Node", "Node", "Node_L", "Node_R"}
        orphans = [
            alias
            for alias in set(self.elements) - connected
            if self.elements[alias]["kind"] not in grouping
        ]
        for alias in sorted(set(orphans) - self.allowed_orphans):
            self.add(
                int(self.elements[alias]["line"]),
                "warning",
                "element '{}' has no relationships; the C4 checklist expects every "
                "element to be connected".format(alias),
            )

    def scan_fallback(self) -> None:
        title_ok = False
        # Front matter ("--- / title: ... / ---") is the form that also renders a
        # caption above the diagram, so accept it as well as the %% title: comment.
        in_front_matter = False
        for number, raw in enumerate(self.lines, start=1):
            if raw.strip() == "---":
                in_front_matter = not in_front_matter
                continue
            if in_front_matter:
                front = FRONT_MATTER_TITLE_RE.match(raw)
                if front:
                    title_ok = True
                    if ENTITY_RE.search(front.group("text")):
                        self.add(
                            number,
                            "error",
                            "HTML entity in the title: spell it out in plain text",
                        )
            if not in_front_matter and number > 1:
                break
        for number, raw in enumerate(self.lines, start=1):
            match = TITLE_COMMENT_RE.match(raw)
            if match:
                title_ok = True
                if ENTITY_RE.search(match.group("text")):
                    self.add(
                        number,
                        "error",
                        "HTML entity in the title comment: spell it out in plain text",
                    )
        if not title_ok:
            self.add(
                1,
                "error",
                "fallback diagrams need a title: a '---\\ntitle: <name>\\n---' front "
                "matter block (shown in the render) or a '%% title: <name>' comment",
            )

    def run(self) -> List[Issue]:
        self.scan_ascii()
        self.scan_header()
        if self.header is None:
            return self.issues
        if self.uses_native_c4:
            self.scan_native()
            self.validate_relations()
        else:
            self.scan_fallback()
        return self.issues


def render_smoke_test(path: Path, text: str) -> List[Issue]:
    try:
        import mermaidx
    except ImportError:
        return [
            Issue(
                path,
                0,
                "warning",
                "mermaidx is not installed: render check skipped "
                "(python3 -m pip install mermaidx -i https://pypi.org/simple)",
            )
        ]
    try:
        config = {}
        if DEFAULT_CONFIG.is_file():
            config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        diagram = mermaidx.render(text, config=config) if config else mermaidx.render(text)
        png = diagram.png(scale=1.0, background="#ffffff")
        width, height = png_size(png)
        if width <= 0 or height <= 0:
            raise ValueError("rendered PNG has zero size")
    except Exception as exc:  # report any renderer failure verbatim
        detail = str(exc)
        message = "render failed: {}".format(detail.splitlines()[0][:200])
        if "cannot read property" in detail:
            message += (
                " | hint: a relationship points at a boundary or deployment node, or a "
                "Deployment_Node directly contains a Container; see "
                "references/mermaid-c4-syntax.md"
            )
        elif "Lexical error" in detail:
            message += " | hint: check the title line and unquoted labels for stray text"
        return [Issue(path, 0, "error", message)]
    return []


def collect_targets(inputs: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.mmd")))
        else:
            files.append(path)
    seen = set()
    unique: List[Path] = []
    for path in files:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", help="Mermaid .mmd files or directories to validate")
    parser.add_argument("--no-render", action="store_true", help="skip the render smoke test")
    parser.add_argument("--json", action="store_true", help="emit issues as JSON")
    args = parser.parse_args(argv)

    targets = collect_targets(args.paths)
    if not targets:
        print("no .mmd files found in: {}".format(", ".join(args.paths)), file=sys.stderr)
        return 1

    issues: List[Issue] = []
    checked = 0
    for path in targets:
        if not path.is_file():
            issues.append(Issue(path, 0, "error", "file not found"))
            continue
        text = path.read_text(encoding="utf-8")
        checked += 1
        issues.extend(Validator(path, text).run())
        if not args.no_render:
            issues.extend(render_smoke_test(path, text))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    infos = [issue for issue in issues if issue.severity == "info"]

    if args.json:
        print(
            json.dumps(
                {
                    "files_checked": checked,
                    "errors": len(errors),
                    "warnings": len(warnings),
                    "info": len(infos),
                    "issues": [issue.as_dict() for issue in issues],
                },
                indent=2,
            )
        )
    else:
        for issue in issues:
            location = "{}:{}".format(issue.path, issue.line) if issue.line else str(issue.path)
            print("{}: {}: {}".format(location, issue.severity.upper(), issue.message))
        print(
            "{} file(s) checked: {} error(s), {} warning(s), {} info".format(
                checked, len(errors), len(warnings), len(infos)
            )
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
