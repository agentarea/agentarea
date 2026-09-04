---
title: Grant access to a resource
type: guide
summary: Give a workspace member or an agent read, write or manage access to one agent, skill, MCP server or skill collection through the authorization graph.
prerequisites:
  - /concepts/governance/the-agentarea-model
related:
  - /guides/governance/model-a-custom-relation
  - /guides/governance/review-the-audit-trail
  - /concepts/governance/authorization-basics
last_updated: 2026-07-29
---

# Grant access to a resource

Do this when one person needs access to one object — a colleague who should be
able to edit a single agent, or an agent that needs to read a specific skill.
Grants are per object and per permission bit.

Do not do this to give someone broad access to everything in a workspace; add
them as a workspace member or admin instead. And do not do this to control what
a running agent may *do* — tool restrictions, budgets and approvals are policy
rules, not graph grants. See [set a budget](/guides/governance/set-a-budget) and
[authorize a tool call](/guides/governance/authorize-a-tool-call).

## Prerequisites

- A graph backend enabled: `ACCESS_CONTROL_BACKEND=openfga`. The setting
  defaults to `disabled`, and with it disabled every write here returns HTTP
  503 and the permission service allows everything. **Which stack you started
  decides whether it is on:**

  | You ran | Compose file | Graph |
  |---|---|---|
  | `make up-dev` | `docker-compose.dev.yaml` | on — sets `ACCESS_CONTROL_BACKEND=openfga` and runs OpenFGA |
  | `make up` | `docker-compose.yaml` | **off** — the file names neither the setting nor OpenFGA, so it falls through to `disabled` |
  | Helm | `charts/agentarea` | on when `openfga.enabled=true`, which is the chart default |

  If you are on `make up`, switch to `make up-dev` or set the variable and run
  OpenFGA yourself before continuing.
- You are a workspace admin. Every `/v1/access-control` endpoint requires it.
- The subject is already a member of your workspace, and the object already
  exists in it. Both are checked before the tuple is written.
- Read [the AgentArea model](/concepts/governance/the-agentarea-model) — in
  particular that the three permission bits are independent.

Examples below assume `API=http://localhost:8000` and a bearer token in `$TOKEN`.

## Steps

### 1. Confirm the graph is on

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$API/v1/access-control/graph" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("enabled:", d["enabled"], "nodes:", len(d["nodes"]))'
```

`enabled: false` means no graph backend is configured — stop here and set
`ACCESS_CONTROL_BACKEND` before continuing.

### 2. Choose the relation

The relation you send is mapped onto one of three grant relations on the
resource. Pick by what the subject needs to do:

| Send | Grants | Use when the subject must |
|---|---|---|
| `reader` | `reader` | view, use, execute, connect to, or operate the resource |
| `writer` | `writer` | edit, update or configure it |
| `manager` | `manager` | delete it or change who else has access |

Four legacy names still resolve, so older scripts keep working: `viewers` and
`connectors` map to `reader`, `editors` to `writer`, and `owners` and `operators`
to `manager`.

**The bits do not imply each other.** A subject with only `manager` cannot read
the resource. To give somebody full access, write all three.

### 3. Write the grant

```bash
curl -s -X POST "$API/v1/access-control/relationships" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "namespace": "Agent",
        "object": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "relation": "writer",
        "subject_id": "User:alice@example.com"
      }'
```

`namespace` is one of `Agent`, `MCPServer`, `Skill` or `SkillCollection`. It
selects the repository used to confirm the object belongs to your workspace; the
tuple itself is always written against `resource:<object>`, because all four
kinds are one generic type in the graph.

`subject_id` takes two shapes. Use `User:<user_id>` for a person. Use
`Agent:<agent_uuid>` to let one agent reach a resource in its own right — that
agent must also be in your workspace.

A successful write returns HTTP 201 and `{"ok": true}`. Writes are idempotent, so
repeating one is safe.

### 4. Repeat for each bit you need

```bash
for rel in reader writer manager; do
  curl -s -X POST "$API/v1/access-control/relationships" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"namespace\":\"Agent\",\"object\":\"$AGENT_ID\",\"relation\":\"$rel\",\"subject_id\":\"User:alice@example.com\"}"
done
```

To revoke, send the same body to `DELETE /v1/access-control/relationships`. It
returns HTTP 204.

## Verify

Ask the graph directly. `relation` accepts the same verbs the application uses,
and they are mapped onto the underlying bit:

```bash
curl -s -X POST "$API/v1/access-control/check" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "namespace": "Agent",
        "object": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "relation": "edit",
        "subject_id": "User:alice@example.com"
      }'
```

```json
{"allowed": true}
```

To see *why* it was allowed — direct grant, role assignment, project
inheritance, or workspace admin — resolve the path:

```bash
curl -s -X POST "$API/v1/access-control/resolve" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_id": "User:alice@example.com",
        "resource_kind": "agent",
        "resource_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77"
      }'
```

The response carries `allowed`, `effective_relation`, `verb` and a `paths` array.
`resource_kind` is one of `skill`, `collection`, `mcp` or `agent`.

You can also list what has been written:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/access-control/relationships?namespace=Agent" \
  | python3 -m json.tool
```

## Troubleshooting

**`403 Only a workspace admin may modify the authorization graph`.** Every
endpoint under `/v1/access-control` requires workspace admin, including the read
and check endpoints. Being the resource's owner is not enough.

**`403 Agent:<id> not found in your workspace`.** The object id is wrong, belongs
to another workspace, or you are sending it with the wrong `namespace`. The
lookup uses the namespace to pick the repository, so an MCP server id sent with
`"namespace": "Agent"` fails this way.

**`403 Subject user is not in your workspace`.** Add the person to the workspace
first through `POST /v1/workspaces/{workspace_id}/invitations`. Membership is
resolved from the workspace owner plus the membership table, so a user who has
been invited but has not accepted is not yet grantable.

**`422 Unsupported relation for a resource grant`.** You sent something outside
the accepted set. Use `reader`, `writer` or `manager`.

**`422 Group (subject_set) grants are managed via project/role, not the
explorer`.** This endpoint writes direct grants only. Bundled or group-scoped
access goes through `role` and `role_assignment` objects — see
[model a custom relation](/guides/governance/model-a-custom-relation).

**`503 Graph authorization is disabled` or `Graph authorization write failed`.**
The first means `ACCESS_CONTROL_BACKEND` is `disabled`. The second means OpenFGA
was reachable but rejected or dropped the write; the API deliberately does not
fall back to allowing the operation, so check the OpenFGA container before
retrying.

**The grant exists and the user still cannot read.** Almost always the
independent-bits rule. Check all three separately — `read`, `edit` and `manage`
each need their own tuple, and a `manager` grant confers neither of the others.

**The grant exists and nothing changed in the product.** Only a handful of API
call sites consult the graph today: agent, skill and MCP server edit and delete,
model instance delete, and registered-client use. List and read endpoints are
scoped by workspace in the database and are not graph-filtered, so a grant will
not make a resource appear or disappear from a list.

## Related

- [The AgentArea model](/concepts/governance/the-agentarea-model) — the types and
  inheritance behind these tuples.
- [Model a custom relation](/guides/governance/model-a-custom-relation) — when
  direct grants are not enough.
- [Review the audit trail](/guides/governance/review-the-audit-trail) — note that
  grant changes are not recorded there.
