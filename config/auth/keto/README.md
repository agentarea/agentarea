# Keto (ReBAC) config

Ory Keto provides the relationship-based authorization graph behind
**Govern → Access control** (the ReBAC access explorer).

- `keto.yml` — server config (read `:4466`, write `:4467`, metrics `:4468`). DSN
  is injected from the environment by docker-compose / Helm.
- `namespaces.keto.ts` — the Ory Permission Language (OPL) model: the namespaces
  (`User`, `Workspace`, `SkillCollection`, `Skill`, `MCPServer`, `Agent`), their
  relations, and the permission rewrites that make grants fan out.

## Model in one paragraph

Subjects that receive grants are **users**, **agents**, or
`Workspace:<id>#members` (the default-viewer rule). Skills live in
**collections**; a single grant on a collection (`viewers`/`editors`/`owners`)
fans out to every skill whose `collections` relation points at it. Direct
grants on a skill are the "exceptions". Agents are both subjects (they *use*
skills / *connect* to MCP) and objects (someone *operates* them).

## Relation tuple shapes

```
Workspace:<wid>#members@User:<uid>
Workspace:<wid>#members@Agent:<aid>

SkillCollection:<cid>#parents@Workspace:<wid>
SkillCollection:<cid>#viewers@Agent:<aid>
SkillCollection:<cid>#editors@Agent:<aid>
SkillCollection:<cid>#owners@User:<uid>
SkillCollection:<cid>#viewers@Workspace:<wid>#members   # default viewer

Skill:<sid>#collections@SkillCollection:<cid>           # membership / fan-out
Skill:<sid>#owners@Agent:<aid>                          # direct exception

MCPServer:<mid>#connectors@Agent:<aid>
Agent:<aid>#operators@User:<uid>
```

## Permissions (computed)

| Namespace        | Permission  | Resolves to                                              |
|------------------|-------------|---------------------------------------------------------|
| `Skill`          | `use`       | direct viewer/editor/owner ∪ any collection's `use`     |
| `Skill`          | `configure` | direct editor/owner ∪ any collection's `configure`      |
| `Skill`          | `manage`    | direct owner ∪ any collection's `manage`                |
| `SkillCollection`| `use/configure/manage` | viewers / editors / owners                    |
| `MCPServer`      | `connect`   | connectors ∪ operators                                  |
| `Agent`          | `operate`   | operators ∪ owners                                      |

The backend `KetoPermissionService` maps the generic
`check(user, permission, resource_type, resource_id)` onto these.
