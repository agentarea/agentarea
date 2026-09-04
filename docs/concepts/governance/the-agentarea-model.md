---
title: The AgentArea authorization model
type: concept
summary: The OpenFGA types, relations and tuples AgentArea deploys, how ownership and projects nest, and which parts of the API actually consult the graph.
prerequisites:
  - /concepts/governance/authorization-basics
related:
  - /concepts/governance/policy-engine
  - /concepts/governance/tool-authorization
  - /concepts/governance/audit
last_updated: 2026-07-29
---

# The AgentArea authorization model

AgentArea models resource access as ReBAC in OpenFGA. Agents, skills, MCP servers
and clients are not four permission systems — they are one generic `resource`
type whose access is derived from the project it belongs to and the grants
written on it. Everything you own is a node; everything you can reach is an edge.

This is relationship-based access control, not role-based. Roles exist in the
model, but they are objects in the graph carrying independent permission bits,
not a global role table. Read
[authorization models](/concepts/governance/authorization-basics) first if that
distinction is unfamiliar.

## The problem

An agent platform accumulates object kinds quickly: agents, skills, skill
collections, MCP server instances, registered clients, files, projects. Modelling
each as its own permission namespace means the same four relations get
copy-pasted per kind, and every new kind is a schema change plus a migration.

At the same time, the objects nest. A workspace contains projects; projects
contain resources; a project can contain another project. Granting a team access
to a project must reach the resources inside it without writing a grant per
resource, and revoking it must not leave orphans behind.

## The deployed model

The model is `config/auth/openfga/model.fga`, schema 1.1, loaded into OpenFGA at
startup. Seven types:

```
type User
type Agent

type Workspace
  relations
    define members: [User, Agent]
    define admin: [User]

type role
  relations
    define can_read:   [User:*, Agent:*]
    define can_write:  [User:*, Agent:*]
    define can_manage: [User:*, Agent:*]

type role_assignment
  relations
    define assignee: [User, Agent]
    define role:     [role]
    define can_read:   assignee and can_read from role
    define can_write:  assignee and can_write from role
    define can_manage: assignee and can_manage from role

type project
  relations
    define workspace:       [Workspace]
    define parent:          [project]
    define role_assignment: [role_assignment]
    define reader:  [User, Agent]
    define writer:  [User, Agent]
    define manager: [User, Agent]
    define can_read:   reader  or can_read   from role_assignment or can_read   from parent or admin from workspace
    define can_write:  writer  or can_write  from role_assignment or can_write  from parent or admin from workspace
    define can_manage: manager or can_manage from role_assignment or can_manage from parent or admin from workspace

type resource
  relations
    define project:         [project]
    define role_assignment: [role_assignment]
    define reader:  [User, Agent]
    define writer:  [User, Agent]
    define manager: [User, Agent]
    define can_read:   reader  or can_read   from role_assignment or can_read   from project
    define can_write:  writer  or can_write  from role_assignment or can_write  from project
    define can_manage: manager or can_manage from role_assignment or can_manage from project
```

Four decisions are worth naming.

**One generic `resource` type.** An agent, a skill, an MCP server and a
registered client are all `resource:<uuid>`. Which kind of thing a resource is
lives in the database, not the graph. Adding a new governed kind needs no model
change and no migration.

**Independent permission bits.** `can_read`, `can_write` and `can_manage` do not
imply each other. A role granting only `can_write` yields `can_write: true` with
`can_read: false` and `can_manage: false`. This is the Google IAM
predefined-role shape, not the GitHub "editors are also viewers" shape, and it is
why the ownership writer grants all three bits explicitly rather than granting
`manager` and expecting the rest to follow.

**`project` is the governance container and it nests.** A nested project is the
folder — there is no separate folder type. Authorization inherits downward:
`... from parent` carries a grant from a project into its children, and
`... from project` carries it from a project into its resources. `admin` on the
workspace short-circuits all three bits at every level below it.

**Agents are principals.** `[User, Agent]` on `reader`/`writer`/`manager` and
`[User:*, Agent:*]` on the role bits means an agent can hold a grant in its own
right. An agent is therefore both a subject and — as an artifact someone
configures and deletes — a `resource:<id>` object.

Note the mixed casing: `User`, `Agent` and `Workspace` are PascalCase while
`role`, `role_assignment`, `project` and `resource` are lowercase. The lowercase
types landed additively beside the pre-existing identity types rather than
replacing them, and the casing is a live artifact of that. Object references are
literal, so a tuple is written `resource:<uuid>#reader@User:<id>`.

## How ownership and projects are seeded

Two writers keep the graph in step with the database.

When a workspace is created, `seed_workspace` writes three tuples so the
workspace is usable without manual setup:

```
Workspace:<ws>#members@User:<creator>
Workspace:<ws>#admin@User:<creator>
project:<ws>-root#workspace@Workspace:<ws>
```

Every workspace therefore has a root project named `<workspace_id>-root`, and
because `project.can_*` rolls up `admin from workspace`, a workspace admin
manages that root project and everything under it.

When a governed resource is created, `grant_resource_owner` attaches it to the
root project and grants the creator all three bits:

```
resource:<id>#project@project:<ws>-root
resource:<id>#reader@User:<creator>
resource:<id>#writer@User:<creator>
resource:<id>#manager@User:<creator>
```

Both writers are idempotent — an "already exists" response from the graph is
treated as success — and both raise HTTP 503 rather than continuing silently when
the graph write fails.

## How a check is made

Application code does not speak OpenFGA. It calls
`require_permission(permission, resource_type, resource_id, user_id)`, which
resolves a `PermissionService` from the DI container. When the backend is
OpenFGA, that service maps a generic verb onto one of the three bits and issues a
single `Check` against `resource:<id>`:

| Verb | Bit |
|---|---|
| `view`, `use`, `read`, `execute`, `operate`, `connect` | `can_read` |
| `edit`, `write`, `update`, `configure` | `can_write` |
| `manage`, `own`, `delete` | `can_manage` |

A verb outside that table is denied and logged. Two resource types,
`model_instance` and `model`, are listed as ungoverned and return allow without
consulting the graph — they are scoped by the workspace layer only, and a graph
check would deny a legitimate owner who has no tuple.

When OpenFGA is unreachable the client raises rather than coercing the answer to
allow or deny, so an outage surfaces as a failure at the call site instead of a
silent posture change.

The relationship explorer at `/v1/access-control` exposes the same graph:
`GET /graph` and `GET /relationships` read it, `POST`/`DELETE /relationships`
write and revoke resource grants, `POST /check` and `POST /resolve` answer single
questions, and `POST /sync` reconciles them. Every one of those endpoints
requires workspace admin, and both the object and the subject are asserted to be
inside the caller's workspace before a tuple is touched. When no graph backend is
configured, reads report `enabled: false` and writes return HTTP 503.

## Admission at the request edge

Resource checks answer "may you change this object". A separate decision answers
"may you invoke this agent at all", and it does not consult the graph.

Every protocol edge resolves a caller the same way. `resolve_user_context_from_token`
turns a Kratos JWT, an `aat_` API key or a Hydra token into one user context, so a
credential that works over REST works everywhere. `authorize_agent_action` then
decides, taking a subject, one of four action verbs — `agent:read`, `agent:write`,
`agent:execute`, `agent:stream` — and the agent's workspace, in this order:

1. A public grant on the agent allows anyone, including an anonymous caller.
2. An anonymous caller with no public grant is denied.
3. An authenticated caller whose accessible workspaces include the agent's
   workspace is allowed.
4. Everything else is denied.

The engine behind step 3 is workspace scope, not the relationship graph. The
function is written so a per-principal ReBAC grant can be added there without
touching a call site, and that substitution has not been made. Admission composes
with the policy engine rather than replacing it: the edge decides whether a run
may start, the policy engine decides what the run may do.

## Why not RBAC

Calling this model RBAC is not loose phrasing, it is a different system. AgentArea
resources are shared per object, inside a hierarchy, by ordinary users — the exact
workload where a global role table becomes one role per object.

The graph is shaped to keep role *bundles* through the `role` and
`role_assignment` types while moving the *scope* onto an edge. One `role:editor`
object would attach to any number of projects and resources through separate
assignment nodes, so the bundle stays small and the scope stays exact. Compared
with a role column on each table, that shape buys inheritance without a cascade
job: a grant on a parent project reaches nested projects and their resources with
no additional rows.

Read that paragraph as the model's design, not as behaviour you can rely on
today. The types are deployed and validated, but nothing writes role,
role_assignment or project-parent tuples yet, so the working part of the graph is
ownership and workspace-admin cascade. What is already real is the part that
motivated the choice: resource grants are per object, and a workspace admin
reaches everything through the root project without a grant per resource.

The cost is that OpenFGA is a second datastore. Ownership writes are distributed
writes that can fail independently of the database transaction, checks are network
calls on the request path, and a set of invariants the graph cannot express has to
be enforced by the writer instead — one workspace and one parent per project, one
project per resource, same-workspace edges only, an acyclic project graph, and
each `role_assignment` attached to exactly one object.

## Limits
- **The graph is off by default in code.** `ACCESS_CONTROL_BACKEND` defaults to
  `disabled`, in which case the permission service is
  `WorkspaceScopedPermissionService`, whose `check` returns `True`
  unconditionally. The only boundary in that configuration is workspace scoping
  in the repository layer. The shipped `docker-compose.dev.yaml` and the Helm
  chart both set the backend to `openfga`, so a standard deployment has the graph
  on — but a process started without those environment variables does not.
- **Seven call sites check, and one of them is a no-op.** `require_permission` is
  called on agent edit and delete, skill edit and delete, MCP server edit and
  delete, and model instance delete. The model instance call cannot deny
  anything: `model_instance` is on the ungoverned list, so that check returns
  allow before the graph is consulted. Read and list endpoints are scoped by
  workspace in the database and are not graph-filtered; the client's
  `list_objects` reverse lookup is implemented but has no caller. A user inside a
  workspace can therefore list resources they hold no tuple for, and registered
  clients are not graph-checked at all.
- **Roles are modelled but never written.** No code in this repository creates a
  `role` or `role_assignment` tuple, and no endpoint exposes one — the
  relationship explorer explicitly rejects group grants and refers the caller to
  `project`/`role`, which has no writer. The `role_assignment` branch of every
  `can_*` rule therefore never matches. The same holds for `project:<id>#parent`
  and for `reader`/`writer`/`manager` written directly on a project: the model
  supports them and nothing populates them.
- **Five tuple shapes exist in practice.** Everything the graph decides today
  rests on `Workspace#members`, `Workspace#admin`, `project#workspace`,
  `resource#project`, and `resource#reader|writer|manager`. Only `User` subjects
  are ever written, despite `Agent` being accepted everywhere a `User` is.
- **Projects are not yet graph-authorized.** The `project` type exists, nests and
  inherits, but resources are attached to the workspace root project by the
  ownership writer. Access to project-scoped data elsewhere in the platform is
  still workspace-string-scoped.
- **Role bits will need writing for both subject shapes.** The role bits accept
  `[User:*, Agent:*]`. Whenever a role writer does land, a role written only for
  `User:*` will silently deny agent assignees — a fail-closed footgun that shows
  up only when a real agent runs.
- **Tool calls do not touch this graph.** Authorization for invoking a tool is a
  policy-engine decision, not a graph lookup. See
  [tool authorization](/concepts/governance/tool-authorization).
- **Public execution is not expressible.** The public-grant hook that
  `authorize_agent_action` consults first is a placeholder that always returns
  false. There is no tuple, flag or endpoint that makes an agent publicly
  executable, so every caller must be authenticated and in the agent's workspace.
- **Only A2A calls the edge authorizer explicitly.** The A2A endpoint routes
  through `authorize_agent_action`. The REST execute path enforces the same
  outcome implicitly, through workspace-scoped repositories rather than a call to
  the shared decision point, so the two paths agree today by construction rather
  than by sharing the check.

## Related

- [Authorization models](/concepts/governance/authorization-basics) — the
  vocabulary this page assumes.
- [The policy engine](/concepts/governance/policy-engine) — the other
  authorization surface, and why it is separate.
- [Tool authorization](/concepts/governance/tool-authorization) — what a tool
  call clears, and what it does not.
- [Audit](/concepts/governance/audit) — what a grant change leaves behind.
