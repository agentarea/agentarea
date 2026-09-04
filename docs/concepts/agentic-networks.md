---
title: Agentic networks
type: concept
summary: AgentArea models a workspace as a private network of agents, with zone labels for what talks to the outside world — and enforces some of that model, not all of it.
prerequisites:
  - /concepts/workspaces-projects-resources
related:
  - /concepts/control-and-data-plane
  - /concepts/governance/the-agentarea-model
  - /concepts/sandbox/why-a-sandbox
  - /concepts/open-core
last_updated: 2026-07-29
---

# Agentic networks

An agent that can reach anything is an agent you cannot reason about. AgentArea
borrows the mental model network engineers already have — the virtual private
cloud — and applies it to agents: a workspace is a private network, the agents
and tools inside it are hosts, and the interesting question is always which of
them can reach the outside world.

The analogy is a way to see your system. Read this page for what it buys you and,
equally, for where it stops being enforcement and becomes a picture.

## The problem

A workspace accumulates agents, skills, MCP server instances and triggers. After
a few dozen entities, two questions get hard to answer at a glance:

- **Which of these can talk to the internet?** An MCP server instance that calls
  the GitHub API is a very different risk from one that reads a local file.
- **Where does data leave the governed environment?** Untrusted model output plus
  an unnoticed outbound connection is the shape of most agent data-exfiltration
  incidents.

A flat list of resources answers neither. Neither does a generic node graph where
every entity is the same grey box.

## How AgentArea approaches it

Three ideas, in decreasing order of how strongly they are enforced.

### The workspace is the isolation boundary

This one is real enforcement, in the database, on every query. Every entity
inherits `WorkspaceScopedMixin` and every repository extends
`WorkspaceScopedRepository`, whose `_get_workspace_filter()` constrains reads to
the caller's `accessible_workspaces`. A row belonging to another workspace is not
filtered out of the UI — it is never selected.

`UserContext` (`user_id`, `workspace_id`, `accessible_workspaces`) is required to
construct any repository, via `RepositoryFactory`. There is no ambient
"current workspace" to forget to pass, which is what makes the boundary hold.

### Relationships decide access inside the boundary

Within a workspace, authorization is relationship-based (ReBAC), evaluated by
OpenFGA or Ory Keto. The deployed model defines these types:

| Type | Relations |
|---|---|
| `Workspace` | `admin`, `members` |
| `project` | `workspace`, `parent`, `manager`, `writer`, `reader`, `role_assignment`, `can_manage`, `can_write`, `can_read` |
| `resource` | `project`, `manager`, `writer`, `reader`, `role_assignment`, `can_manage`, `can_write`, `can_read` |
| `role`, `role_assignment` | `can_manage`, `can_write`, `can_read` (and `assignee`, `role`) |
| `User`, `Agent` | subject types, no relations |

Access flows down: a `resource` inherits from its `project`, a `project` from its
`parent` and its `workspace`. This is the part of the network model that actually
gates requests.

### Zone labels describe external reach

Skills and MCP server instances carry a `network_scope` field with three values:

| Value | Meaning |
|---|---|
| `private` | No external connectivity. The default. |
| `ingress` | Receives traffic from outside, such as a webhook trigger. |
| `egress` | Calls out to an external service, such as an MCP server instance reaching a vendor API. |

The network view renders these as three zones left to right — gateway, governed
internal, egress — and highlights edges that cross from internal to egress, so an
ungoverned outbound path is visible without running an audit.

Read the next section before you rely on that field for anything.

## What is enforced and what is presented

This distinction matters more than the analogy, so it gets its own table.

| Claim | Status |
|---|---|
| Workspace data isolation | **Enforced.** Repository-level filter on `workspace_id`, applied to every read. |
| Project and resource permissions | **Enforced.** OpenFGA/Keto relation checks, fail-closed. |
| `network_scope` on skills and MCP instances | **Presentation and filtering only.** Stored on the entity, usable as a list filter, rendered in the UI. No policy consults it and nothing blocks traffic because of it. |
| Zone-crossing risk highlight | **Presentation only.** A visual indicator, not an interception point. |
| Per-agent-pair communication rules | **Does not exist.** There is no rule format for "agent A may message agent B" and no component that evaluates one. |

The `network_scope` field was introduced as the foundation for later policy
enforcement, and that later has not arrived. Setting a skill to `private` today
documents an intention; it does not confine anything. Treat the zone view as an
inventory that makes risk legible, not as a control that removes it.

Actual egress restriction, where it exists, comes from the sandbox data plane
rather than from `network_scope`. The operator selects one deployment-level
internet policy; task callers cannot choose or weaken it. The built-in
Kubernetes provider renders that choice as NetworkPolicy, while external
providers must enforce the equivalent contract themselves. It remains unaware
of the label on the skill.

## Why not enforce network_scope directly?

The obvious move is to make `network_scope` binding: refuse to start an MCP
server instance marked `private` if it opens a socket. Two things make that
harder than it sounds.

**The label is a declaration, not an observation.** `network_scope` defaults to
`private` and is set by whoever registers the skill or instance. Enforcing an
unverified self-declaration gives you the appearance of a control while an
incorrect label silently grants an exemption. Enforcement has to derive from
something the platform observes — the pod's actual network policy — rather than
from a field a user typed.

**The enforcement point is in a different plane.** Traffic leaves from a sandbox
pod or an MCP container in the data plane. The label lives on a control-plane
row. Making the label binding means propagating it into pod-level network policy
on every backend the manager supports, and failing closed when a backend cannot
express it. That is a real project, not a validation rule.

So the honest position is the current one: the model is enforced at the workspace
and relation layer, where the platform genuinely mediates every access, and the
zone layer is descriptive until the pod-level plumbing exists to back it. Naming
that gap is better than letting you infer a containment guarantee that is not
there.

## Why not a generic agent graph?

The first version of the network view was a flat React Flow graph: every entity a
node, every relationship an identical edge. It was abandoned because it answered
neither operator question. A graph that shows you forty nodes and eighty edges
communicates that your system is complicated, which you knew.

Zones beat a force-directed layout here because the reader arrives with a
specific question — what touches the outside? — and zone membership answers it
positionally, before any edge is traced. The cost is that the layout is static
rather than draggable, and it gets crowded at high entity counts.

## Limits

- **`network_scope` is not a security control.** It does not block, filter, or
  restrict any connection. Do not use it as a compensating control in a threat
  model or a compliance narrative.
- **There is no inter-agent communication policy.** Any agent in a workspace can
  address any other agent in that workspace it has a relation to. Documentation
  elsewhere that shows a `network_policy` YAML block or an `A2ABridge` that
  raises `CommunicationDeniedError` describes something that was never built.
- **Cross-workspace isolation depends on `accessible_workspaces` being correct.**
  It is resolved during authentication. A token minted with a broader workspace
  list than intended widens the boundary, and no lower layer will catch it.
- **Zone classification for triggers is automatic and coarse.** Webhook triggers
  are ingress; everything else is private. A trigger that reaches out on a
  schedule is still labelled private.
- **The label does not survive into the data plane.** Nothing in the Go MCP
  manager or the sandbox runtime reads `network_scope`.

## Related

- [Workspaces, projects, and resources](/concepts/workspaces-projects-resources) — the scoping model this network sits on
- [Control plane and data plane](/concepts/control-and-data-plane) — why the enforcement point and the label live in different places
- [The AgentArea authorization model](/concepts/governance/the-agentarea-model) — the relations that are enforced
- [Why a sandbox](/concepts/sandbox/why-a-sandbox) — where egress restriction actually happens
