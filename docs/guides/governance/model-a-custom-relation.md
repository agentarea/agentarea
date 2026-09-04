---
title: Model a custom relation
type: guide
summary: Add a relation or a role bundle to the OpenFGA authorization model, test it with the fga CLI, and roll it out so the running platform picks it up.
prerequisites:
  - /concepts/governance/the-agentarea-model
  - /guides/governance/grant-resource-access
related:
  - /guides/governance/grant-resource-access
  - /concepts/governance/authorization-basics
  - /concepts/governance/the-agentarea-model
last_updated: 2026-07-29
---

# Model a custom relation

Do this when direct `reader`/`writer`/`manager` grants cannot express what you
need — a reusable permission bundle assigned to many objects, a new inheritance
edge, or a relation for a resource kind that needs its own semantics.

Do not do this to add a new *kind* of governed object. Agents, skills, MCP servers
and clients are all `resource:<uuid>` and the kind lives in the database, so a new
kind needs no model change at all. And do not do this for runtime restrictions —
tool rules, budgets and approvals are policy rules, not graph relations.

Model changes are shared infrastructure. The same store backs workspace
membership and every resource grant, so a bad rollout breaks all authorization at
once. Make changes additive.

## Prerequisites

- The `fga` CLI installed. Every step below depends on it.
- Write access to `config/auth/openfga/` in the repository.
- A dev stack you can restart: `ACCESS_CONTROL_BACKEND=openfga` with
  `ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP=true` and
  `ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=true`, which is what
  `docker-compose.dev.yaml` sets. Start it with `make up-dev`, not `make up` —
  the latter runs `docker-compose.yaml`, which names neither the setting nor
  OpenFGA, so the backend falls through to its `disabled` default and none of
  the verification steps below will work.
- Read [the AgentArea model](/concepts/governance/the-agentarea-model) — you are
  editing exactly what that page describes.

Three files move together:

| File | Role |
|---|---|
| `config/auth/openfga/model.fga` | the DSL you edit — the source of truth |
| `config/auth/openfga/model.fga.yaml` | CLI test fixture: tuples plus assertions |
| `config/auth/openfga/authorization-model.json` | generated API payload the platform loads at boot |

## Steps

### 1. Choose the shape

**A role bundle** is the usual answer, and it needs no model change at all. Create
a `role` object carrying the bits, then bind it to a subject and one object with a
`role_assignment`. This is how you get "reviewer" or "operator" across many
projects without a relation per bundle:

```
role:reviewer#can_read@User:*
role:reviewer#can_write@User:*

role_assignment:ra-42#assignee@User:alice
role_assignment:ra-42#role@role:reviewer
project:analytics#role_assignment@role_assignment:ra-42
```

Reach for a **new relation** only when the graph itself must derive something it
cannot today — a second inheritance edge, or a bit that is not read, write or
manage.

### 2. Edit the model

Add to `config/auth/openfga/model.fga`. Keep changes additive: a new type, or a
new relation on an existing type. Changing or removing an existing relation
breaks live tuples that reference it.

```
type resource
  relations
    define project:         [project]
    define role_assignment: [role_assignment]
    define reader:  [User, Agent]
    define writer:  [User, Agent]
    define manager: [User, Agent]
    define auditor: [User, Agent]
    define can_read:   reader  or can_read   from role_assignment or can_read   from project
    define can_write:  writer  or can_write  from role_assignment or can_write  from project
    define can_manage: manager or can_manage from role_assignment or can_manage from project
    define can_audit:  auditor or can_manage from project
```

Two conventions the existing model follows. Identity types are PascalCase
(`User`, `Agent`, `Workspace`); governance types are lowercase (`role`,
`role_assignment`, `project`, `resource`). And permission bits are **independent**
— do not write `can_write: writer or can_manage`, because the model deliberately
has no roll-up.

### 3. Add tests before you validate

Every new relation needs at least one positive and one negative assertion in
`config/auth/openfga/model.fga.yaml`. Add tuples to the shared `tuples` block and
a case to `tests`:

```yaml
  - user: User:auditor1
    relation: auditor
    object: resource:agent1
```

```yaml
  - name: auditor can audit but cannot write
    check:
      - user: User:auditor1
        object: resource:agent1
        assertions:
          can_audit: true
          can_write: false
          can_manage: false
```

The negative assertion is the one that catches an accidental roll-up.

### 4. Validate and test

```bash
cd config/auth/openfga
fga model validate --file model.fga
fga model test --tests model.fga.yaml
```

Both must pass before you go further. `validate` catches DSL errors; `test` runs
every assertion in the fixture, including the ones that were already there — a
change that breaks existing inheritance shows up here.

### 5. Generate the deployable model

The JSON is generated, never hand-edited:

```bash
fga model transform --file model.fga > authorization-model.json
cp authorization-model.json ../../../charts/agentarea/files/openfga/authorization-model.json
```

Both copies must move together. The compose stack mounts the `config/` copy at
`/app/config/auth/openfga/authorization-model.json`; the Helm chart packages the
`charts/` copy as a ConfigMap mounted at
`/etc/agentarea/openfga/authorization-model.json`.

### 6. Roll it out

Restart the API and the worker. Both bootstrap OpenFGA at startup: they find or
create the store named by `ACCESS_CONTROL_OPENFGA_STORE_NAME`, compare the model
on disk against the models already in the store, write it if it is new, and use
the returned model id for the rest of the process lifetime.

```bash
docker compose -f docker-compose.dev.yaml restart agentarea-backend agentarea-worker
```

Because OpenFGA versions models rather than replacing them, existing tuples keep
working against the previous version while the new one becomes current. That is
why additive changes are safe and destructive ones are not.

## Verify

**The CLI tests pass.** This is the gate; run it before anything else:

```bash
cd config/auth/openfga && fga model test --tests model.fga.yaml
```

**The running platform loaded the new model.** Write a tuple that uses the new
relation and check it end to end. Both endpoints require workspace admin:

```bash
curl -s -X POST "$API/v1/access-control/relationships" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"namespace":"Agent","object":"'"$AGENT_ID"'","relation":"reader","subject_id":"User:alice@example.com"}'

curl -s -X POST "$API/v1/access-control/check" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"namespace":"Agent","object":"'"$AGENT_ID"'","relation":"read","subject_id":"User:alice@example.com"}'
```

```json
{"allowed": true}
```

**Existing authorization still works.** Check a workspace membership and a
pre-existing resource grant that you did not touch. A model change that silently
broke inheritance shows up here rather than in your new tests.

## Troubleshooting

**The new relation is not recognised after a restart.** The bootstrap compares
models by normalized content, ignoring ids. If your edited model is byte-identical
in structure to one already in the store, it reuses that model id and writes
nothing — which is correct. If it genuinely differs and is still not picked up,
check that `ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=true` and that
`ACCESS_CONTROL_OPENFGA_MODEL_PATH` points at the file you regenerated. With
auto-apply off, the process uses whatever `ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID`
names and your file is ignored.

**It works in compose and not in Kubernetes.** You regenerated
`config/auth/openfga/authorization-model.json` and forgot the copy under
`charts/agentarea/files/openfga/`. They are two files and nothing keeps them in
sync automatically.

**Agents are denied where users are allowed.** Role bits are typed
`[User:*, Agent:*]` and both must be written per enabled bit. A role object
created with only `User:*` tuples silently denies every agent assignee — a
fail-closed footgun that only appears when a real agent runs.

**A `manager` grant does not confer read.** Working as designed. The bits are
independent; write all three when you mean full access. See
[grant access to a resource](/guides/governance/grant-resource-access).

**`422 Unsupported relation for a resource grant` when writing through the API.**
The relationship endpoint accepts a fixed set of relation names and maps them onto
`reader`, `writer` or `manager`. A relation you added to the model is not
automatically writable through that endpoint — it needs a code change, or write
the tuple directly against OpenFGA during development.

**`422 Group (subject_set) grants are managed via project/role`.** The
relationship endpoint writes direct grants only. Bundled access is exactly what
`role` and `role_assignment` are for; write those tuples through OpenFGA or a
migration script.

**Authorization broke everywhere after the change.** You made a destructive edit —
renamed or removed a relation that live tuples reference. Restore the previous
`model.fga`, regenerate both JSON copies, and restart. OpenFGA keeps prior model
versions, so re-pinning `ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID` to the
last known-good id is the fastest rollback while you fix the DSL.

## Related

- [The AgentArea model](/concepts/governance/the-agentarea-model) — the model you
  are extending, and the invariants the writer enforces outside the graph.
- [Grant access to a resource](/guides/governance/grant-resource-access) — the
  direct grants that cover most needs.
- [Authorization models](/concepts/governance/authorization-basics) — why roles
  are objects here rather than a table.
