# <System Name> - C4 Architecture Documentation

<!--
Template for docs/c4/README.md. Replace every <placeholder>, delete sections that
do not apply, and keep the diagram index in sync with the files on disk.
All prose and diagram text must be English.
-->

## Overview

<One paragraph: what the system in scope is, who it serves, and what the
documentation covers. State the system boundary explicitly.>

**Scope:** <name of the software system in scope>
**Source of truth:** generated from the repository on <date> by the `c4` skill;
diagrams are regenerated with `python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams`.

## Diagram index

| View | Purpose | Source | Image |
| --- | --- | --- | --- |
| System context (L1) | <audience and question answered> | [diagrams/01-system-context.mmd](diagrams/01-system-context.mmd) | [PNG](png/01-system-context.png) / [SVG](svg/01-system-context.svg) |
| Container (L2) | <audience and question answered> | [diagrams/02-container.mmd](diagrams/02-container.mmd) | [PNG](png/02-container.png) / [SVG](svg/02-container.svg) |

## Legend

| Notation | Meaning |
| --- | --- |
| Person | Human actor or role interacting with the system. |
| Software system | Highest-level abstraction; internal systems are blue, external systems grey. |
| Container | Separately runnable application or data store; cylinder = data store. |
| Component | Logical grouping of code inside one container. |
| Solid arrow | Unidirectional relationship; label states intent and technology. |
| Dashed border | External or out-of-scope element. |

## System context (L1)

![System Context diagram](png/01-system-context.png)

<Two or three sentences: who uses the system, what it delivers, which external
systems it depends on, and why those external systems are outside the boundary.>

## Container (L2)

![Container diagram](png/02-container.png)

<Two or three sentences per container: responsibility, technology, who talks to
it, and which data it owns. Call out inter-process protocols.>

## Component (L3) - <container name>

<!-- Delete this section when no component diagram was produced. -->

![Component diagram for <container>](png/03-component-<container>.png)

<Which container is decomposed, what each component is responsible for, and which
part of the code implements it.>

## Dynamic view - <flow name>

<!-- Delete this section when no dynamic diagram was produced. -->

![Dynamic diagram for <flow>](png/05-dynamic-<flow>.png)

<Numbered narrative matching the diagram steps, including error paths that matter.>

## Deployment view - <environment>

<!-- Delete this section when no deployment diagram was produced. -->

![Deployment diagram for <environment>](png/06-deployment.png)

<Environment(s) covered, infrastructure nodes, scaling/instance layout, and
protocols between nodes.>

## Evidence

Every element below is traceable to the repository; keep this table in sync when
regenerating diagrams.

| Element | Abstraction | Evidence |
| --- | --- | --- |
| <name> | Container | `<path or config key>` |
| <name> | External system | `<dependency, client, or configuration>` |
| <name> | Component | `<package/module path>` |

## Assumptions and open questions

| Item | Status | Note |
| --- | --- | --- |
| <element or relationship inferred, not observed> | Assumption | <why it was assumed> |
| <missing information: SLO, owner, environment, retention> | Open question | <who can answer> |

## Review checklist status

- [ ] Every diagram has a title stating diagram type and scope.
- [ ] Every diagram has a legend consistent with the others.
- [ ] Every element has a name, type, and short description.
- [ ] Every container and component states its technology.
- [ ] Every relationship is labelled with intent and, where relevant, protocol.
- [ ] Acronyms are expanded, and colour/shape meanings are documented.
- [ ] Assumptions and open questions above have been reviewed by a system owner.

## Regenerating

```bash
python3 <skill-dir>/scripts/validate_c4.py docs/c4/diagrams
python3 <skill-dir>/scripts/render_c4.py --src docs/c4/diagrams
```

`manifest.json` records the source hash, dimensions, and render status of every
diagram. Only changed diagrams are re-rendered; use `--force` to render all.

---

This documentation follows the C4 model by Simon Brown (<https://c4model.com/>).
