---
title: Configure the platform registries
type: guide
description: "Set the registries every workspace sees in the Helm values, choose their mode and trust, retire one, and opt in to syncing workspace registries."
prerequisites:
  - /self-host/kubernetes
  - /concepts/integration/registry-and-catalog
related:
  - /guides/agents/add-a-skill-registry
  - /self-host/configuration
  - /self-host/upgrades
last_updated: 2026-10-20
---

Platform registries are the catalog sources every workspace on the deployment
sees: the LLM provider and model specs, the MCP server catalog, the curated
skills, the built-in agents and the event source types. You set them in the
chart values, and the `registry-reconcile` Job applies them on every install and
upgrade. Edit them to point an air-gapped install at your own index, to add or
drop a source, or to change how one is mirrored.

A workspace adds its own sources itself, without the operator; see
[add a skill registry](/guides/agents/add-a-skill-registry).

## Prerequisites

<Info>
- The chart installed as in [deploy on Kubernetes](/self-host/kubernetes), with
  object storage configured. A `mirror` skills registry stores its content
  there during the Job; without storage credentials the Job fails that
  registry.
- Each source reachable from the cluster: an index URL, or a GitHub repository.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="List the registries">
    `registryReconcile.registries` is a list of entries, passed to the Job as
    the `REGISTRIES_CONFIG` environment variable and read by
    `agentarea-api reconcile`.

    | Key | Default | Description |
    |---|---|---|
    | `name` | required | The registry's name; unique among platform registries. The Job finds an existing registry by it. |
    | `source_url` | required unless `active: false` | An index URL, or `owner/repo` for `source_type: github`. |
    | `type` | detected | `mcp_servers`, `skills`, `llm_providers`, `llm_models`, `agents`, `bundles` or `source_types`. Detected from the index's top-level key when unset, at the cost of one extra fetch. A `github` entry is `skills` without a fetch; any other `type` on it is refused. |
    | `source_type` | `url` | `url` or `github`. A `github` source holds skills. |
    | `source_ref` | default branch | `github`: the branch, tag or commit to read. |
    | `source_path` | repository root | `github`: the folder whose skill folders are indexed. |
    | `mode` | `mirror` | `mirror` copies each skill's content to object storage at sync; `upstream` keeps the index and fetches a version on first install or run. |
    | `trust` | `official` | `official`, `verified`, `community` or `private`; shown on every card and usable in install policy. |
    | `recommendation_priority` | `100` | Weight of the whole source in the Explore "Recommended" order, lower first. The shipped curated sources use `10`. |
    | `credentials_secret_ref` | none | A secret of the `platform` workspace, by name or id, that a sync reads the source with: a GitHub token for a private repository. The registry keeps the reference and resolves it at each sync; the value is never copied. A `skills` registry with credentials must be `mode: mirror`. A name no platform secret has fails that registry. |
    | `description` | none | Shown with the registry. |
    | `active` | `true` | `false` retires the registry; see below. |

    ```yaml
    registryReconcile:
      enabled: true
      registries:
        - name: system-skills-curated
          source_url: https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/skills.json
          recommendation_priority: 10
        - name: acme-skills
          type: skills
          source_type: github
          source_url: acme/agent-skills
          source_path: skills
          mode: mirror
          trust: verified
    ```

    Setting `registries` in your values replaces the whole default list, so
    copy the shipped entries you want to keep from the chart's `values.yaml`.
  </Step>

  <Step title="Change an existing registry">
    For a registry that already exists, the Job applies every field of its
    entry, logs the fields that changed (`Updated mode, source_url`), and then
    syncs it: the source (`source_url`, `source_type`, `source_ref`,
    `source_path`), `mode`,
    `trust`, `recommendation_priority` and `credentials_secret_ref`. A field the
    entry leaves out takes its default, so dropping `credentials_secret_ref`
    drops the credentials. A changed source or `mode` clears the stored ETag,
    so that sync reads the source in full: `upstream` to `mirror` stores every
    skill's content; `mirror` to `upstream` deletes nothing already stored.
    Items the new source does not publish leave the catalog as any dropped
    item does.

    A changed `type` is refused: retire the old name and add the new source
    under a new name.
  </Step>

  <Step title="Retire a registry">
    ```yaml
        - name: system-skills-community
          active: false
    ```

    The Job deactivates the registry and takes all its items out of the
    catalog. Items nothing uses are deleted. An item an installed skill uses
    moves to the item with the same `external_id` in a registry the same run
    reconciled, if one exists; otherwise it stays, and the installed skill keeps
    working and shows "Removed upstream". Retired entries run after every
    active one, so their replacements are synced first.

    Removing an entry from the list instead leaves the registry and its items
    exactly as the last sync left them.
  </Step>

  <Step title="Sync workspace registries, if you want them scheduled">
    ```yaml
    registryReconcile:
      workspaceRegistries: true
    ```

    The Job then also runs with `--workspace-registries`: it syncs every active
    registry a workspace admin added, each under its own workspace. A tenant's
    failing source is recorded on that registry and reported in the log; it
    does not fail the Job.

    The chart runs the Job on install and upgrade only and ships no schedule.
    For periodic syncs, run the same command, `agentarea-api reconcile
    --workspace-registries`, with the Job's environment from a CronJob of your
    own. Concurrent runs are safe: each registry is synced under a PostgreSQL
    advisory lock, and a run that finds it held skips that registry.
  </Step>
</Steps>

## Verify

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=registry-reconcile
```

Each registry prints `Reconciling: <name>`, then `Created registry` or `Found
existing registry`, then `Synced: {...}` with its counts, and the run ends with
`Reconcile complete: N succeeded, 0 failed`. A retired one prints `Retired
registry: <id> (<n> items deleted)`. In the web app, **Settings → Registries**
lists them under **Platform registries** with their trust and last sync.

## Troubleshooting

<AccordionGroup>
  <Accordion title="&quot;a mirror registry stores its content in object storage&quot;">
    The Job has no storage credentials. The chart passes the same storage
    variables to the Job as to the backend; check `global.storage` and the
    storage Secret. Or set `mode: upstream` for that registry.
  </Accordion>
  <Accordion title="&quot;Skipped <name>: another reconcile is syncing it&quot;">
    Another run holds that registry's lock. If no other run exists, the
    database connection goes through a transaction-mode pooler, which keeps the
    session lock past the run; point the Job at the database directly or at a
    session-mode pooler.
  </Accordion>
  <Accordion title="A synced registry shows the old content">
    The source's ETag (or head commit) did not change, so it was not read again.
    Run `agentarea-api reconcile --force` to re-read every source.
  </Accordion>
  <Accordion title="Installs or syncs of GitHub sources fail with rate-limit errors">
    A platform registry has no credentials, so its GitHub API calls and every
    install-time fetch of an `upstream` skill are anonymous and share GitHub's
    limit of 60 requests an hour per IP address. File contents are read from
    `raw.githubusercontent.com`, outside that limit. Prefer `mirror` with an
    index that carries `tree_sha` for each skill.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Registry and catalog" icon="lightbulb" href="/concepts/integration/registry-and-catalog">
    Scope, mode, trust, pinned installs and content by digest
  </Card>
  <Card title="Add a skill registry" icon="robot" href="/guides/agents/add-a-skill-registry">
    What a workspace admin adds on top of the platform's
  </Card>
  <Card title="Deploy on Kubernetes" icon="server" href="/self-host/kubernetes">
    The install whose Jobs run the reconcile
  </Card>
  <Card title="Upgrades" icon="server" href="/self-host/upgrades">
    When the Job runs again
  </Card>
</Columns>
