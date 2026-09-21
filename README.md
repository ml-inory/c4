# c4

Codex skill that documents software architecture with the [C4 model](https://c4model.com/):
English Markdown, editable Mermaid diagram sources, and PNG/SVG renders produced by
[mermaidx](https://pypi.org/project/mermaidx) with no browser or Node.js required.

## Install

```bash
ln -sfn "$PWD" "${CODEX_HOME:-$HOME/.codex}/skills/c4"
```

## Usage

```bash
# inside a target repository
python3 <skill-dir>/scripts/validate_c4.py docs/c4/diagrams
python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams
python3 <skill-dir>/scripts/check_layout.py docs/c4/svg
```

Or ask Codex: `Use $c4 to document this repository's architecture.`
See [SKILL.md](SKILL.md) for the workflow and [references/c4-model.md](references/c4-model.md)
for the model itself.

Licensed under the MIT License; the C4 model is by Simon Brown (c4model.com).
