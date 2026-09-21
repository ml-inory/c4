---
name: c4
description: Create and maintain C4 model documentation for software systems, producing English Mermaid diagram sources plus PNG and SVG images. Use when Codex needs to visualize or document the architecture of a repository, service, or platform, draw C4 diagrams (system landscape, system context, container, component, code, dynamic, deployment) with Mermaid, generate architecture documentation with embedded images, assess or review an existing architecture description against the C4 model, or refresh architecture diagrams after code changes.
---

# C4 Model Architecture Documentation

## Overview

Turn a codebase or a verbal architecture description into a documented C4 model: English Markdown, one editable Mermaid source per diagram, and PNG/SVG renders produced by the `mermaidx` PyPI package (no browser, no Node.js).

Before authoring diagrams, read [references/c4-model.md](references/c4-model.md) for the model itself and [references/mermaid-c4-syntax.md](references/mermaid-c4-syntax.md) for the exact syntax, escaping rules, and known failure modes.

## Workflow

Work through these steps in order.

1. **Pick the input mode.** A target path in the request means codebase analysis. Only a description means authoring from the description, where every element the user did not state is an assumption.
2. **Select the views.** Apply the rules in "Level selection" below; do not generate diagrams that add no value.
3. **Gather elements with evidence.** In codebase mode, collect aliases, names, technologies, descriptions, and the file/config each element came from.
4. **Author one `.mmd` file per diagram** under `docs/c4/diagrams/` in the target project.
5. **Validate:** `python3 <skill-dir>/scripts/validate_c4.py docs/c4/diagrams`.
6. **Render:** `python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams`. The script installs `mermaidx` if it is missing, applies the C4 layout config, restructures the SVG so connector lines cannot cover text, and writes `png/`, `svg/`, and `manifest.json`.
7. **Check the layout:** `python3 <skill-dir>/scripts/check_layout.py docs/c4/svg`. Mermaid's C4 layout puts relationship labels on the edge path, so labels can land on boxes or be clipped. If it reports problems, run `python3 <skill-dir>/scripts/fit_labels.py docs/c4/diagrams --apply` and render again; repeat until it is clean.
8. **Write `docs/c4/README.md`** from [assets/c4-doc-template.md](assets/c4-doc-template.md), embedding the rendered PNGs and linking the sources.
9. **Report** the files produced, the assumptions and open questions, and which review checklist items still need a human decision.

`<skill-dir>` is the directory containing this file.

## Level selection

| View | When to produce it |
| --- | --- |
| L1 System Context | Always. One diagram for the system in scope, its users, and the external systems it depends on. |
| L2 Container | Always. The deployable/runnable units inside the system, plus technology choices. |
| L3 Component | Only when the code shows cohesive internal parts of one container (packages/modules/classes with distinct responsibilities) and that container matters to the story. Produce one component diagram per container. |
| L4 Code | Only on explicit request or when one component's implementation is the subject. Use a Mermaid `classDiagram`, not C4 syntax. |
| System Landscape | When the system in scope is one of several systems or team boundaries matter. |
| Dynamic | When a runtime flow (sign-in, order, ingestion) must be explained as an ordered interaction. |
| Deployment | When real deployment topology is readable from IaC/config (compose, k8s, Terraform, systemd). |

c4model.com states that not every level is required; system context and container diagrams are enough for most teams. Prefer three clear diagrams over seven padded ones.

## Extraction in codebase mode

Collect evidence before inventing boxes:

- **People/actors:** user-facing entry points, role definitions, auth configuration, product docs.
- **Containers:** `Dockerfile`, `docker-compose.yml`, k8s manifests, serverless configs, `pom.xml`, `build.gradle`, `*.csproj`, `go.mod`, `package.json`, `pyproject.toml`, `Cargo.toml`, plus process entry points (`main`, `cmd/`, `bin/`, `src/*/__main__.py`) and independent schedulers/workers.
- **Components:** top-level packages/modules inside one container with a cohesive responsibility; controllers, services, repositories, adapters. Do not create one component per file.
- **External systems:** runtime calls to third-party APIs, identity providers, payment/e-mail services, cloud services, managed queues and databases outside the scope.
- **Relationships:** imports between modules, HTTP/gRPC clients, database access, queue producers/consumers, CLI invocations. Capture the technology (protocol, driver, format) when the code shows it.

Keep evidence out of the diagrams and record it in the Evidence table of `docs/c4/README.md`. Mark anything inferred rather than observed as an assumption, and list what the code cannot answer (SLOs, team ownership, cost, non-functional requirements).

## Authoring rules

- Write all diagram text in English, Latin characters only; non-ASCII text renders as missing glyphs.
- Use native Mermaid C4 syntax (`C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment`) as the first choice.
- Fall back to the C4-styled `flowchart` template in [references/flowchart-fallback.md](references/flowchart-fallback.md) only when native syntax fails or cannot express the layout. Add a `<!-- fallback: <reason> -->` note at the top of the `.mmd` file so the deviation is auditable.
- Name files `00-system-landscape.mmd`, `01-system-context.mmd`, `02-container.mmd`, `03-component-<container>.mmd`, `04-code-<component>.mmd`, `05-dynamic-<flow>.mmd`, `06-deployment.mmd`.
- Use short lowerCamel aliases (`bankingSystem`, `webApp`) that stay stable across regenerations; never renumber aliases that already exist.
- Give every element a short description and every relationship a verb plus technology where known (`Reads/writes`, `JDBC`).
- Keep each diagram between roughly 3 and 15 concrete elements; split anything larger into a second diagram or a lower level.
- Connect every element to at least one other element; an unconnected box is a defect.

## Minimal example

```mermaid
C4Container
    title Container diagram for Internet Banking System
    Person(customer, "Personal Banking Customer", "A customer of the bank with personal bank accounts")
    System_Boundary(banking, "Internet Banking System") {
        Container(webApp, "Web Application", "Java, Spring MVC", "Delivers the static content and the SPA")
        Container(spa, "Single-Page Application", "JavaScript, Angular", "Provides banking functionality in the browser")
        ContainerDb(db, "Database", "Oracle Database Schema", "Stores user registration and account data")
    }
    System_Ext(mail, "E-mail System", "The internal Microsoft Exchange e-mail system")
    Rel(customer, webApp, "Uses", "HTTPS")
    Rel(spa, db, "Reads from and writes to", "JDBC")
    Rel(webApp, mail, "Sends e-mail using", "SMTP")
```

## Validation

Run `scripts/validate_c4.py` before every render. It reports, per file and line:

- hard errors: missing or duplicated diagram header, missing title, duplicate aliases, relationships pointing at boundaries or undeclared aliases, HTML entities on the `title:` line, boundary nesting deeper than three, render failure;
- warnings: non-ASCII text, orphan elements, elements without a description, non-native syntax.

Fix hard errors and review warnings before rendering; render failures include the applicable workaround from `references/mermaid-c4-syntax.md`.

## Rendering

```bash
python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams
```

Defaults: PNG at `docs/c4/png/`, SVG at `docs/c4/svg/`, manifest at `docs/c4/manifest.json`, `scale=2.0`, white background, `default` theme. The script:

1. imports `mermaidx`, or installs it with `python3 -m pip install mermaidx -i https://pypi.org/simple` (some corporate/mirror indexes do not carry the package);
2. renders each `.mmd` to PNG and SVG using `assets/mermaid-config.json`, which widens the C4 shape margin so relationship labels have room (`--config` overrides it, `--no-config` disables it);
3. skips diagrams whose source hash and render options both match the manifest, unless `--force` is given;
4. records dimensions, paths, and render status in `manifest.json`.

Use `--check-only` to validate rendering without writing output, and `--scale`,
`--width`/`--height`, `--theme`, and `--background` to change the raster output.
Keep the default `--scale 2` for documentation: it puts label text at roughly 24-32
pixels in the PNG, so the file is readable at 100% zoom. The script warns when a
render drops below 1.5 image pixels per diagram pixel (text too small) or grows
wider than 6000px (file too heavy). Passing `--width` overrides the scale and is
only worth it when a diagram is meant to be viewed fit-to-width.

Readability comes from the diagram's own size, not from the export resolution: a
wide C4 diagram always needs zooming when it is scaled to fit a page. When a
diagram is still hard to read, split it (one story per diagram), shorten element
descriptions, or link the SVG - it stays crisp at any zoom.

Manual fallback if the script cannot be used:

```bash
python3 -m pip install mermaidx -i https://pypi.org/simple
mermaidx -i docs/c4/diagrams/02-container.mmd -o docs/c4/png/02-container.png --scale 2 -b "#ffffff"
```

## Output contract

Write only inside the target project:

```
docs/c4/
├── README.md          # index, narrative, evidence table, assumptions
├── diagrams/*.mmd     # editable Mermaid sources (committed)
├── png/*.png          # PNG renders referenced by README.md
├── svg/*.svg          # vector renders for editing and high-resolution use
└── manifest.json      # source hashes, render status, image dimensions
```

Embed images with relative paths, for example `![Container diagram](png/02-container.png)`.

## Verified pitfalls

These were reproduced against mermaid.js v11 through `mermaidx`; the same rules apply to any Mermaid C4 renderer.

- Relationships must target concrete elements, never boundary aliases: `Rel(app, deploymentNode, ...)` and `Rel(user, systemBoundary, ...)` abort with `TypeError: cannot read property 'x' of undefined`.
- A `Deployment_Node` that directly contains a `Container` renders, but adding a relationship that points at that node fails. Nest a `Deployment_Node` inside it, or use the flowchart fallback.
- Never put HTML entities such as `&amp;` on the `title:` line (lexical error); a raw `&` is fine. Entities are fine inside quoted labels and descriptions.
- Keep labels Latin-only: `mermaidx` bundles DejaVu Sans, so CJK characters become tofu boxes.
- Quote every label/description and use `<br/>` for line breaks inside them.
- Use `UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")` to control native C4 layout; there is no `direction` keyword in C4 diagrams.

## Resources

- [references/c4-model.md](references/c4-model.md) - abstractions, diagram types, notation, and the review checklist.
- [references/mermaid-c4-syntax.md](references/mermaid-c4-syntax.md) - keywords, escaping rules, working examples, failure modes.
- [references/flowchart-fallback.md](references/flowchart-fallback.md) - C4-styled flowchart templates for unsupported cases.
- [assets/c4-doc-template.md](assets/c4-doc-template.md) - template for the generated `docs/c4/README.md`.
- `scripts/validate_c4.py`, `scripts/render_c4.py` - validation and rendering.
