---
title: Add a skill registry to a workspace
type: guide
description: "Point a workspace at a GitHub repository or index URL of skills, sync it, and decide by policy which registries members may install from."
prerequisites:
  - /concepts/integration/registry-and-catalog
related:
  - /guides/agents/attach-skills
  - /self-host/catalog-registries
  - /reference/policy-syntax
  - /concepts/agents/skills
last_updated: 2026-10-20
---

Add a registry when your team keeps skills (or agent definitions) in its own
repository and wants them in the workspace's catalog next to the platform's. Only
this workspace sees them, installs are pinned to a version, and the same install
policy governs them as every other source.

Do not add a registry for a single skill you want once; import it from its GitHub
URL instead, as in [attach skills](/guides/agents/attach-skills). And do not use
a workspace registry to change what every workspace sees; that is a platform
registry, set by the operator in the
[chart values](/self-host/catalog-registries).

## Prerequisites

<Info>
- You are an admin of the workspace. Members can list registries; adding,
  changing, syncing and removing them is the admin's.
- For a private repository: a workspace secret holding a GitHub token that can
  read it.

Examples assume `API=http://localhost:8000`, a bearer token in `$TOKEN`, your workspace slug in `$WORKSPACE`, and its id in `$WORKSPACE_ID`.
</Info>

In the web app, everything below is on **Settings → Registries**
(`/w/<workspace>/settings/registries`) and **Policies**.

## Steps

<Steps titleSize="h3">
  <Step title="Choose the source">
    <Tabs>
      <Tab title="GitHub repository">
        Every folder holding a `SKILL.md` is one skill. `source_url` is
        `owner/repo`; `source_ref` is a branch, tag or commit (the default
        branch when unset); `source_path` limits the index to one folder (the
        repository root when unset). The skill's name comes from the
        `SKILL.md` frontmatter, else from the folder name.

        A GitHub registry holds skills only, and at most 200 skill folders.
      </Tab>
      <Tab title="Index URL">
        A JSON or YAML document in the platform format, served over public
        `https`: at most 5 MB as JSON, 1 MB as YAML, and 2,000 entries. A
        skills index has one top-level `skills` list; an agents index, `agents`.
        Each skill names its content by a GitHub pointer:

        ```json
        {
          "skills": [
            {
              "name": "pdf-forms",
              "description": "Read and fill PDF forms",
              "source": {
                "type": "github",
                "repo": "acme/skills",
                "path": "skills/pdf-forms",
                "ref": "<40-hex commit sha>",
                "tree_sha": "<40-hex tree sha of skills/pdf-forms>"
              }
            }
          ]
        }
        ```

        `tree_sha` is the version: without it the entry is never flagged as
        updated. An entry may carry an inline `content` body instead of
        `source`.
      </Tab>
    </Tabs>
  </Step>

  <Step title="Choose mode and trust">
    | Field | Pick | When |
    |---|---|---|
    | `mode` | `mirror` (default) | Every skill's content is copied at sync. Installs and runs never reach the source. Pick it for a private repository, and whenever the source may go away. |
    | `mode` | `upstream` | Only the index is kept; a version's content is fetched the first time it is installed or run. Pick it for a large public source most of which nobody installs. |
    | `trust` | `private` (default) | Your own source. |
    | `trust` | `community` | A third-party source you have not vetted. Policy can refuse every `community` registry at once. |

    A registry with credentials is always `mirror`: the token is used to sync,
    never to install. `official` and `verified` are reserved to platform
    registries.
  </Step>

  <Step title="Add the registry">
    ```bash
    curl -s -X POST "$API/v1/workspaces/$WORKSPACE/workspace-registries" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d '{
            "name": "acme-skills",
            "source_type": "github",
            "source_url": "acme/skills",
            "source_path": "skills",
            "mode": "mirror",
            "trust": "private",
            "credentials_secret_id": "<secret id>"
          }'
    ```

    Omit `credentials_secret_id` for a public repository. For an index, send
    `"source_type": "url"` and the index URL as `source_url`. Send
    `"registry_type": "agents"` for an agents index; the default is `skills`.
    The response carries the registry's `id`.

    The registry keeps the secret's id and reads its value only during a sync.
    The token is sent to GitHub; an index URL is always fetched without it.
  </Step>

  <Step title="Sync it">
    ```bash
    curl -s -X POST \
      "$API/v1/workspaces/$WORKSPACE/workspace-registries/<registry-id>/sync" \
      -H "Authorization: Bearer $TOKEN"
    ```

    ```json
    {"new_specs": 3, "updates_flagged": 0, "unchanged": 0, "total": 3,
     "skipped": 0, "skipped_items": []}
    ```

    A sync runs in the request, with a 120-second deadline, and a workspace may
    start one per minute. An unchanged source (the same head commit or ETag) is
    not read again; add `?force=true` to read it anyway. Unless the operator
    enabled scheduled syncing of workspace registries, a registry changes only
    when you sync it.
  </Step>

  <Step title="Restrict where members install from">
    Install rules are policy rules on the workspace (or on a user) with effect
    `allow` or `deny` and one of these targets:

    | Target | Matches |
    |---|---|
    | `registry:<registry id>` | One registry, platform or workspace |
    | `registry_trust:<level>` | Every registry of `official`, `verified`, `community` or `private` |
    | `registry:github` | Skills imported straight from a GitHub URL (trust `community`) |

    A deny always wins. Once any allow rule exists, installs come only from what
    an allow names. To allow your own registries and the platform's official
    ones, and nothing else:

    ```bash
    for target in "registry_trust:private" "registry_trust:official"; do
      curl -s -X POST "$API/v1/workspaces/$WORKSPACE/policies" \
        -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
        -d '{"subject_type": "workspace", "subject_id": "'"$WORKSPACE_ID"'",
             "target": "'"$target"'", "effect": "allow"}'
    done
    ```

    In the web app: **Policies → New rule**, rule type **Installs**, then
    **Allow installs only from** or **Deny installs from**, and pick trust
    levels, registries or **Direct GitHub imports**.

    The rules apply to new installs, updates, edits of catalog items, direct
    GitHub imports, and every task that uses a skill from a registry or a
    GitHub import, installed or not. A skill installed before the rule is not
    offered to new tasks once the rule denies its registry, and activating it
    fails with the rule; it stays in the workspace and comes back when the rule
    is lifted. Skills the workspace wrote itself are not affected.
  </Step>
</Steps>

## Verify

Read the registry back:

```bash
curl -s "$API/v1/workspaces/$WORKSPACE/workspace-registries" \
  -H "Authorization: Bearer $TOKEN"
```

`last_synced_at` is set, `last_sync_error` is `null`, and `item_count` is the
number of skills found. On **Settings → Registries** the registry is under
**Workspace registries**; the platform's own are listed below it under
**Platform registries**, read-only.

In **Explore**, the registry's skills carry a badge with its name and
trust, for example `acme-skills · Private`. Install one, then confirm a refused
source answers `403` with the rule that decided it.

## Troubleshooting

<AccordionGroup>
  <Accordion title="Sync answers 502 with a reason">
    The reason is a classification of what went wrong, never the source's own
    text: `GitHub answered 404` (wrong repository, or a private one without
    credentials), `the source answered HTTP 403`, `the source is not a valid
    JSON or YAML index`. The same text is stored in `last_sync_error`.
  </Accordion>
  <Accordion title="&quot;holds more than 200 skills&quot; or &quot;GitHub truncated the tree&quot;">
    The repository is too large to index in one sync. Set `source_path` to the
    folder that holds the skills.
  </Accordion>
  <Accordion title="Sync answers 429">
    A workspace may start one sync per minute. Wait and retry.
  </Accordion>
  <Accordion title="Adding the registry answers 400">
    The message names the rule: an index URL must be public `https`; a
    workspace registry's trust is `private` or `community`; a skills registry
    read with credentials must be `mirror`.
  </Accordion>
  <Accordion title="Removing the registry answers &quot;retired&quot;">
    Installed skills still use some of its items. The registry leaves the
    catalog and stops syncing; those skills keep working and show **Removed
    upstream**. It is deleted once nothing uses its items.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Registry and catalog" icon="lightbulb" href="/concepts/integration/registry-and-catalog">
    Scope, mode, trust, pinned installs and content by digest
  </Card>
  <Card title="Attach skills to an agent" icon="robot" href="/guides/agents/attach-skills">
    Install a skill from the catalog, update it, attach it
  </Card>
  <Card title="Configure the platform registries" icon="server" href="/self-host/catalog-registries">
    The registries every workspace sees
  </Card>
  <Card title="Policy syntax" icon="book" href="/reference/policy-syntax">
    Every target, effect and subject a rule accepts
  </Card>
</Columns>
