---
title: Authorization model
type: reference
summary: The deployed OpenFGA types, relations and permission bits, the verb mappings applied on top of them, and the settings that select a graph backend.
prerequisites:
  - /concepts/governance/the-agentarea-model
related:
  - /reference/policy-syntax
  - /reference/limits
  - /guides/governance/grant-resource-access
  - /guides/governance/model-a-custom-relation
last_updated: 2026-07-29
---

# Authorization model

The relationship graph that authorizes access to resources. Authority for this
page is `config/auth/openfga/model.fga`; the deployable payload
`config/auth/openfga/authorization-model.json` is generated from it.

## Synopsis

```
model
  schema 1.1

type User

type Agent

type Workspace
  relations
    define members: [User, Agent]
    define admin: [User]

type role
  relations
    define can_read: [User:*, Agent:*]
    define can_write: [User:*, Agent:*]
    define can_manage: [User:*, Agent:*]

type role_assignment
  relations
    define assignee: [User, Agent]
    define role: [role]
    define can_read: assignee and can_read from role
    define can_write: assignee and can_write from role
    define can_manage: assignee and can_manage from role

type project
  relations
    define workspace: [Workspace]
    define parent: [project]
    define role_assignment: [role_assignment]
    define reader: [User, Agent]
    define writer: [User, Agent]
    define manager: [User, Agent]
    define can_read: reader or can_read from role_assignment or can_read from parent or admin from workspace
    define can_write: writer or can_write from role_assignment or can_write from parent or admin from workspace
    define can_manage: manager or can_manage from role_assignment or can_manage from parent or admin from workspace

type resource
  relations
    define project: [project]
    define role_assignment: [role_assignment]
    define reader: [User, Agent]
    define writer: [User, Agent]
    define manager: [User, Agent]
    define can_read: reader or can_read from role_assignment or can_read from project
    define can_write: writer or can_write from role_assignment or can_write from project
    define can_manage: manager or can_manage from role_assignment or can_manage from project
```

Identity types are PascalCase; governance types are lowercase. Object references
are literal, so a tuple reads `resource:<uuid>#reader@User:<id>`.

## Fields

### `Workspace`

| Relation | Accepts | Grants |
|---|---|---|
| `members` | `User`, `Agent` | Membership only. Not consumed by any `can_*` computation. |
| `admin` | `User` | All three bits on every `project` under the workspace, and transitively on their resources. |

### `role`

| Relation | Accepts | Grants |
|---|---|---|
| `can_read` | `User:*`, `Agent:*` | The read bit to any assignment referencing this role. |
| `can_write` | `User:*`, `Agent:*` | The write bit. |
| `can_manage` | `User:*`, `Agent:*` | The manage bit. |

A role is a bag of independent bits. Each enabled bit must be written for both
`User:*` and `Agent:*`; a bit written only for `User:*` denies agent assignees.

### `role_assignment`

| Relation | Accepts | Grants |
|---|---|---|
| `assignee` | `User`, `Agent` | The subject the assignment binds. |
| `role` | `role` | The bundle whose bits apply. |
| `can_read` | computed | `assignee` intersected with `can_read from role`. |
| `can_write` | computed | `assignee` intersected with `can_write from role`. |
| `can_manage` | computed | `assignee` intersected with `can_manage from role`. |

Attach each assignment to exactly one object; attaching one assignment to several
objects amplifies its bits across all of them.

### `project`

| Relation | Accepts | Grants |
|---|---|---|
| `workspace` | `Workspace` | The owning workspace, enabling the `admin` cascade. |
| `parent` | `project` | Downward inheritance of all three bits. |
| `role_assignment` | `role_assignment` | Bundled grants. |
| `reader` / `writer` / `manager` | `User`, `Agent` | Direct grant of the matching bit. |
| `can_read` / `can_write` / `can_manage` | computed | Direct relation, or the same bit from an assignment, or from `parent`, or `admin from workspace`. |

### `resource`

| Relation | Accepts | Grants |
|---|---|---|
| `project` | `project` | Upward link; inherits all three bits downward from the project. |
| `role_assignment` | `role_assignment` | Bundled grants. |
| `reader` / `writer` / `manager` | `User`, `Agent` | Direct grant of the matching bit. |
| `can_read` / `can_write` / `can_manage` | computed | Direct relation, or the same bit from an assignment, or from `project`. |

Agents, skills, MCP servers and registered clients are all `resource:<uuid>`.
Which kind a resource is lives in the database, not the graph.

## Values

### Permission bits

`can_read`, `can_write` and `can_manage` are independent. None implies another. A
role granting only `can_write` yields `can_write: true` with `can_read: false`
and `can_manage: false`.

### Verb to bit — permission service

Applied by `require_permission` and the DI-resolved permission service.

| Verb | Bit |
|---|---|
| `view`, `use`, `read`, `execute`, `operate`, `connect` | `can_read` |
| `edit`, `write`, `update`, `configure` | `can_write` |
| `manage`, `own`, `delete` | `can_manage` |

A verb outside this map is denied and logged at warning level.

### Verb to bit — relationship explorer

Applied by the `/v1/access-control` check endpoint. Note the absence of `update`.

| Verb | Bit |
|---|---|
| `use`, `view`, `read`, `operate`, `connect`, `execute` | `can_read` |
| `configure`, `edit`, `write` | `can_write` |
| `manage`, `own`, `delete` | `can_manage` |

A value that is neither a mapped verb nor one of the three bits returns
`allowed: false` without querying the graph.

### Relation aliases accepted on write

The explorer write endpoint maps a submitted relation onto a resource grant.

| Submitted | Written |
|---|---|
| `reader`, `viewers`, `connectors` | `reader` |
| `writer`, `editors` | `writer` |
| `manager`, `owners`, `operators` | `manager` |

Anything else is rejected. A `subject_set` (group) body is rejected; bundled
access goes through `role` and `role_assignment`.

### Namespaces accepted by the explorer

| Namespace | Used for |
|---|---|
| `Agent`, `MCPServer`, `Skill`, `SkillCollection` | Confirming the object belongs to the caller's workspace |

The namespace selects a repository for that check only. The tuple written or
checked is always against `resource:<object>`.

### Subject forms accepted on write

| Form | Validation |
|---|---|
| `User:<user_id>` | Must be the workspace owner, a membership row, or the caller. |
| `Agent:<agent_uuid>` | Must resolve in the caller's workspace. |

### Seeded tuples

On workspace creation:

| Tuple |
|---|
| `Workspace:<ws>#members@User:<creator>` |
| `Workspace:<ws>#admin@User:<creator>` |
| `project:<ws>-root#workspace@Workspace:<ws>` |

On governed resource creation:

| Tuple |
|---|
| `resource:<id>#project@project:<ws>-root` |
| `resource:<id>#reader@User:<creator>` |
| `resource:<id>#writer@User:<creator>` |
| `resource:<id>#manager@User:<creator>` |

The root project id is the workspace id suffixed with `-root`. Both writers are
idempotent; an "already exists" response is treated as success.

## Enforcement

| Surface | Status |
|---|---|
| Agent edit, agent delete | `Check` enforced |
| Skill edit, skill delete | `Check` enforced |
| MCP server edit, MCP server delete | `Check` enforced |
| Model instance delete | Called, but `model_instance` is ungoverned — returns allow without a graph query |
| Registered client use | `Check` enforced |
| Read and list endpoints | **Not graph-filtered.** Scoped by workspace in the database. |
| Reverse lookup (`list_objects`) | **Implemented, no callers.** |
| Project-scoped data | **Not graph-authorized.** Resources attach to the workspace root project; other project scoping is workspace-string-based. |
| Tool invocation | **Not in this graph.** Decided by the policy engine. See [policy rule syntax](/reference/policy-syntax). |

| Resource type | Behaviour |
|---|---|
| `model_instance`, `model` | Ungoverned. Return allow without querying the graph. |
| Anything else | Treated as `resource:<id>` and fails closed with no tuples. |

| Condition | Behaviour |
|---|---|
| Graph unreachable | The client raises. The check does not coerce to allow or deny. |
| Backend `disabled` | The permission service returns `True` for every check. |
| Graph write fails | HTTP 503. The operation does not proceed. |
| Explorer endpoints | All require workspace admin, including reads and checks. |

Invariants the graph cannot express, enforced by the writer instead: one
workspace and one parent per project, one project per resource, same-workspace
edges, an acyclic project graph, one object per `role_assignment`, and resource
kind resolved from the database.

## Defaults and overrides

`ACCESS_CONTROL_BACKEND` accepts `disabled`, `keto` or `openfga`.

| Source | Value |
|---|---|
| Code default | `disabled` |
| `docker-compose.dev.yaml` (`make up-dev`) | `openfga` |
| `docker-compose.yaml` (`make up`) | **Absent.** Names neither the setting nor OpenFGA, so the code default applies. |
| Helm chart | `openfga` when `openfga.enabled=true`, which is the chart default |

`keto.enabled` and `openfga.enabled` are mutually exclusive; the chart fails
rendering if both are set.

| Setting | Code default |
|---|---|
| `ACCESS_CONTROL_OPENFGA_API_URL` | `http://openfga:8080` |
| `ACCESS_CONTROL_OPENFGA_STORE_ID` | `""` (resolved by bootstrap when empty) |
| `ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID` | `None` |
| `ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS` | `10.0` |
| `ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP` | `false` |
| `ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL` | `false` |
| `ACCESS_CONTROL_OPENFGA_STORE_NAME` | `agentarea` |
| `ACCESS_CONTROL_OPENFGA_MODEL_PATH` | `None` |

`docker-compose.dev.yaml` and the Helm chart both set `AUTO_BOOTSTRAP` and
`AUTO_APPLY_MODEL` to `true`. Model paths differ by deployment:

| Deployment | Mount path |
|---|---|
| Compose | `/app/config/auth/openfga/authorization-model.json` |
| Helm | `/etc/agentarea/openfga/authorization-model.json` |

With `AUTO_APPLY_MODEL` enabled the file wins and the returned model id is used
for the process lifetime. With it disabled,
`ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID` is used and the file is ignored.
Bootstrap compares candidate models by normalized content ignoring ids, so an
unchanged model is reused rather than rewritten. When several processes race a
store create, all converge on the earliest store with that name.

## Example

Grant a write-only role bundle on a project, and confirm the bits do not roll up:

```
role:writeonly#can_write@User:*
role:writeonly#can_write@Agent:*

role_assignment:ra2#assignee@User:ub
role_assignment:ra2#role@role:writeonly

resource:res2#role_assignment@role_assignment:ra2
```

```
Check(User:ub, can_write,  resource:res2) -> true
Check(User:ub, can_read,   resource:res2) -> false
Check(User:ub, can_manage, resource:res2) -> false
```

## See also

- [Policy rule syntax](/reference/policy-syntax) — the other authorization
  surface, which governs tool invocation.
- [Limits](/reference/limits) — timeouts and pagination on the graph client.
- [Errors](/reference/errors) — the 403 and 503 responses these checks produce.
- [The AgentArea model](/concepts/governance/the-agentarea-model) — the reasoning
  behind the type set.
