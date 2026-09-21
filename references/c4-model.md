# The C4 Model Reference

Condensed reference for the C4 model by Simon Brown (<https://c4model.com/>). The
model is notation independent and tooling independent; this skill renders it with
Mermaid. Site text and example diagrams are published under CC BY 4.0.

## Contents

- [Abstractions](#abstractions)
- [Diagram types](#diagram-types)
- [Which diagrams to produce](#which-diagrams-to-produce)
- [Notation guidance](#notation-guidance)
- [Review checklist](#review-checklist)
- [Places the model is often misused](#places-the-model-is-often-misused)

## Abstractions

The C4 model describes static structure with four nested abstractions, plus people.

| Abstraction | Definition | Typical examples | Notes |
| --- | --- | --- | --- |
| Person | A human actor, role, persona, or named individual who uses the system. | Banking customer, support agent, administrator, external system owner. | Keep it to the roles that matter for the story; do not enumerate every job title. |
| Software system (internal) | The highest-level abstraction for the system being modelled: something that delivers value to users and that one team builds, owns, and can change the internals of. | "Internet Banking System", "Order Service", a monolith, a platform. | Its boundary usually matches a team and a repository; everything inside is deployed and modified together. |
| Software system (external) | A system the system in scope depends on, or that depends on it, whose internals are not yours to change. | E-mail system, payment provider, identity provider, ERP. | Draw external systems in a distinct colour/shape and never decompose their internals. |
| Container | An application or data store that must be running for the system to work: a separately deployable/runnable unit or a store of data. | Web app, SPA, API application, mobile app, database schema, message broker, serverless function, file system. | Containers are the unit of deployment and of inter-process communication. Not every ASP.NET/Java "container" is an array of objects — that is a component. |
| Component | A group of related functionality encapsulated behind a well-defined interface, inside one container. | Controller, service, repository, adapter, scheduler, module. | Components are not separately deployable; they are a logical grouping of code. |
| Code element | Classes, interfaces, functions, and data structures that implement a component. | `OrderService`, `PaymentGateway`, `Order` aggregate. | Usually generated or drawn only for exceptional cases; UML class or ER diagrams fit better than C4 syntax. |

Non-abstractions that people often confuse with software systems: product domains,
bounded contexts, business capabilities, feature teams, tribes, squads.

## Diagram types

### Static structure

| Diagram | Scope | Primary elements | Audience |
| --- | --- | --- | --- |
| System landscape | An enterprise, organisation, or department. Essentially a system context diagram without a single focus system. | People and software systems. | Technical and non-technical, inside and outside the team. |
| System context (L1) | One software system and everything it interacts with. | The system in scope, its people, external systems. | Technical and non-technical. |
| Container (L2) | One software system. | Containers, people, external systems, plus technology choices. | Technical people inside and outside the team, including operations and support. |
| Component (L3) | One container. | Components, the container's collaborators, other containers/people/systems it talks to. | Software architects and developers. |
| Code (L4) | One component. | Classes, interfaces, functions, data structures. | Developers and maintainers of that component. |

### Supporting diagrams

| Diagram | Scope | Purpose |
| --- | --- | --- |
| Dynamic | A feature, story, or use case across the static model. | Show runtime collaboration and ordering (for example a sign-in flow) with numbered interactions. |
| Deployment | One or more software systems in a single deployment environment (production, staging, ...). | Map container instances onto deployment nodes: infrastructure, execution environments, nested nodes. |

## Which diagrams to produce

- The context and container diagrams are enough for most software development
  teams. Component diagrams pay off for containers whose internals people actually
  change; code diagrams are rarely worth maintaining by hand.
- Choose diagrams that answer a question someone has. A diagram without an audience
  is documentation debt.
- Every diagram must be able to stand alone: title, scope, key/legend, and honest
  labels beat a diagram that only makes sense next to a slide deck.
- Keep one story per diagram. If a container diagram needs more than roughly 15
  elements, split it or zoom in one level.

## Notation guidance

The model does not mandate a notation, but the notation must be explicit and used
consistently:

- Every diagram has a title that states diagram type and scope, for example
  "Container diagram for Internet Banking System".
- Every diagram has a key/legend covering shapes, colours, border styles, line
  types, and arrow heads, including any icon set used (AWS, Azure, ...).
- Every element states its type (person, software system, container, component),
  has a short description, and - for containers and components - its technology.
- Every relationship is unidirectional, labelled with intent and direction, and
  specific ("Reads customer records", not "Uses"). Inter-process relationships
  carry their technology or protocol (HTTPS/JSON, JDBC, AMQP).
- Acronyms are expanded in the diagram or the legend.
- Colour coding is optional but must be consistent within and across diagrams, and
  must survive greyscale printing and colour-blind readers.
- Do not mix abstraction levels in one diagram: a component must not sit next to
  another system's internal container.

## Review checklist

General

- Does the diagram have a title, and is the diagram type and scope obvious?
- Does the diagram have a key/legend?

Elements

- Does every element have a name, a visible type, and a short description?
- Are technology choices clear where they exist (containers, components, stores)?
- Are acronyms, colours, shapes, icons, border styles, and element sizes explained?

Relationships

- Does every arrow have a label describing intent, matching the arrow direction?
- Is the technology/protocol labelled for inter-process relationships?
- Are acronyms, colours, arrow heads, and line styles explained in the legend?

## Places the model is often misused

- Drawing the four levels as a mandatory sequence; the model is a set of views, not
  a process.
- Using containers as "things inside a Docker host" only; a container is any
  separately runnable application or data store.
- Turning components into packages, namespaces, or one box per class.
- Documenting deployment topology on a container diagram instead of a deployment
  diagram.
- Letting diagrams drift from the code: regenerate them from the repository when
  the architecture changes.

## Sources

- C4 model home: <https://c4model.com/>
- Abstractions: <https://c4model.com/abstractions>
- Diagrams: <https://c4model.com/diagrams>
- Notation: <https://c4model.com/diagrams/notation>
- Review checklist: <https://c4model.com/diagrams/checklist>
- Tooling FAQ: <https://c4model.com/tooling>
