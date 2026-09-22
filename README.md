# c4

Codex skill that documents software architecture with the [C4 model](https://c4model.com/):
English Markdown, editable Mermaid diagram sources, and PNG/SVG renders produced by
[mermaidx](https://pypi.org/project/mermaidx) with no browser or Node.js required.

## Install

```bash
ln -sfn "$PWD" "${CODEX_HOME:-$HOME/.codex}/skills/c4"
```

Requires Python 3.9+ and the [`mermaidx`](https://pypi.org/project/mermaidx) renderer.
`render_c4.py` installs `mermaidx` on demand, but a distribution-managed interpreter
(PEP 668) refuses that. Either install it for your user:

```bash
python3 -m pip install --user mermaidx -i https://pypi.org/simple
# add --break-system-packages if pip insists, or use a virtualenv:
python3 -m venv ~/.local/share/c4-venv && ~/.local/share/c4-venv/bin/pip install mermaidx
```

and then run the scripts with that interpreter (`~/.local/share/c4-venv/bin/python3
<skill-dir>/scripts/render_c4.py ...`) if you took the virtualenv route.

## Usage

```bash
# inside a target repository
python3 <skill-dir>/scripts/validate_c4.py docs/c4/diagrams        # source lint
python3 <skill-dir>/scripts/fit_labels.py docs/c4/diagrams --apply --max-shift 24
python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams    # PNG + SVG + manifest
python3 <skill-dir>/scripts/check_arrows.py docs/c4/diagrams       # label ownership, crossings, fan-in
python3 <skill-dir>/scripts/check_layout.py docs/c4/svg            # overlap, clipping, box overflow
```

`fit_labels.py` rewrites the `.mmd` sources, so it runs before the render the checkers
read. `check_arrows.py` and `check_layout.py` are the gate; a diagram is finished when both
are silent and the render has been looked at.

Or ask Codex: `Use $c4 to document this repository's architecture.`
See [SKILL.md](SKILL.md) for the workflow and [references/c4-model.md](references/c4-model.md)
for the model itself.

Licensed under the MIT License; the C4 model is by Simon Brown (c4model.com).
