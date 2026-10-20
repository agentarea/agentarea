---
title: Registry and catalog
type: concept
description: "Registries are sources with a scope, a mode and a trust level; the catalog is their snapshot, and an install pins one version of an item."
prerequisites:
  - /concepts/workspaces-projects-resources
related:
  - /guides/agents/add-a-skill-registry
  - /self-host/catalog-registries
  - /concepts/agents/skills
  - /concepts/integration/bundles
  - /concepts/integration/mcp
last_updated: 2026-10-20
---

A registry is a source of definitions: skills, agents, MCP servers, LLM providers
and models, bundles, event source types. A catalog item is one entry that a
registry's last sync found. A workspace sees the items of every platform
registry plus those of its own registries. An item becomes the workspace's own
only when someone installs it. For a skill, an install is a pin to one version,
and the skill's content lives in object storage under the digest of its files.

## The problem

A catalog has to answer three questions that pull in different directions. Who
sees an entry? Where do its bytes come from? What does a workspace that installed
it actually run?

The obvious design answers all three with one global table. Every workspace sees
everything, the entry's body sits in the row, and an install copies that body.
That fails as soon as a customer wants a private source. It also fails once a
public source turns out to be mostly pointers: a crawled community index
publishes a description and a GitHub link, not the skill. An install that copies
the row copies a stub, and nothing ever fetches the real `SKILL.md`. And a body
that is copied on install and overwritten on sync leaves no way to say which
version a workspace runs.

## How AgentArea approaches it

### A registry has a scope, a mode, a source and a trust level

| Property | Values | What it decides |
|---|---|---|
| `scope` | `platform`, `workspace` | Who sees the items. A `platform` registry is configured by the operator of the deployment and every workspace sees it. A `workspace` registry is added by that workspace's admin and only that workspace sees it. |
| `source_type` | `url`, `github`, `api`, `managed` | Where the index comes from. `url` is an index document in the platform format (JSON or YAML). `github` is a repository whose folders are skills; the platform builds the index itself. A workspace registry may use `url` or `github` only. |
| `mode` | `mirror`, `upstream` | When a skill's content is copied. `mirror` copies every item's content into object storage at sync. `upstream` keeps only the index and fetches a version's content the first time it is installed or run, then keeps it. |
| `trust` | `official`, `verified`, `community`, `private` | A label on every catalog card and installed skill, and a value policy rules can name. A workspace may give its own registry `private` or `community` only. |
| `credentials_secret_ref` | a secret id | The token a sync reads a private source with: a secret of the owning workspace, or of the `platform` workspace for a platform registry (named in the chart values). The registry holds a reference and resolves it at sync time; the value is never copied. |

A workspace registry holds `skills` or `agents`. The other types materialize
platform-wide entities at sync, so only the platform may publish them. Registry
names are unique per scope: a workspace's registry may share a name with a
platform registry or with another workspace's.

A skills registry read with credentials is always mirrored. Credentials are
resolved for a sync only, so an install of an upstream item could not
authenticate.

### The index is a snapshot

A sync reads the source only when it changed. For a `url` source that means the
HTTP `ETag`; for a `github` source, the head commit of `source_ref` (the default
branch when unset). The stored value is prefixed with a parser format version, so
a release that changes parsing re-reads every source once. `force` re-reads
regardless.

When a source changed, the sync upserts every entry it publishes. Entries the
source dropped leave the catalog. One that nothing references is deleted. One
that an install, a fork, a connection or a materialized MCP server still points
at stays, marked out of source; its installed copies keep working and show
"Removed upstream". A source that parses to zero entries retires nothing, because
an empty index is far likelier a broken source than an emptied one.

A sync that skipped an item, such as one that failed validation, does not store
the new ETag, so the next sync reads the source again.

### Skill content is immutable and addressed by digest

A catalog skill's package is stored once under the sha256 of its files. A
platform registry's packages share one area,
`skills/catalog/<digest>/`. A workspace registry's packages live under that
workspace's prefix, `skills/<workspace>/catalog/<digest>/`, so private content
never lands where another tenant reads.

An index entry names its content in one of two ways:

- **A GitHub pointer**: `repo`, `path`, and optionally the `ref` commit and the
  folder's `tree_sha`. Fetching downloads that folder at that commit and checks
  the tree SHA. The tree SHA is also the item's version. A `github` registry
  always produces pointers with both. A pointer without `tree_sha` has the
  version `latest`; fetching reads the folder at `ref` or the branch head and
  computes its tree SHA from the files.
- **An inline `content` body**, which becomes a single `SKILL.md`.

Without credentials, nothing reads GitHub through its REST API, whose anonymous
limit of 60 requests an hour every tenant of a deployment shares. A ref resolves
over git's smart HTTP protocol (`github.com/<repo>.git`, one `ls-refs`
request), the files come from the commit's archive at `codeload.github.com`, and
the folder's tree SHA is computed from them as git computes it. An archive is
read once per commit and process, so a sync that stores several folders of one
commit downloads it once. A registry with credentials reads through the REST
API with its token instead.

In `mirror` mode the sync stores each item's package and records where in the
item's spec, so an install needs no network. In `upstream` mode the first install
or run of a version fetches and stores it; later ones reuse the stored package.
Each process also caches catalog packages by path, up to 64 MB; a digest never
changes, so the cache is never invalidated.

Skills in the database carry metadata: name, description, source, and the
location of the package. Activation reads `SKILL.md` from the package, and
materialization copies the package into the task's sandbox. Once a version has
been stored, runs read it from object storage and never from GitHub.

### An install is a pin

Installing a catalog skill creates a workspace skill row that points at the
item's package and records the item's version in `registry_item_installs`. For a
GitHub pointer that version is the tree SHA of the folder the install fetched,
also when the index names none. Attaching a catalog skill to an agent installs
it the same way.

When a later sync gives the item a different version, the installed skill shows
"update available". Nothing changes until a workspace admin updates it, one skill
at a time or all at once. An update moves the pointer to the new package.

For an installed pointer whose index names no tree SHA, every sync of an
`upstream` registry asks the source which tree the folder is now and keeps that
as the item's version, even when the index itself did not change. The checks run
after the sync has committed, within their own 120-second budget, so a slow
GitHub costs checks and never the sync. They cover at most 50 installed items a
sync, in `external_id` order: one `ls-refs` request per repository and branch,
and the commit's archive, unpacked once for every folder of it, when the branch
moved. A `mirror` registry versions such a pointer by the tree it stored.

Editing an installed skill stores the edited files as a new package of the
workspace's own and points the skill at it. The catalog package is never
written. The skill still records its catalog item, so it still shows
"update available", but it now reads "Customized": update-all skips it, and a
single update replaces the edit only when the admin passes `discard_changes`, and
the edit stays in the skill's history to roll back to.

The same copy-on-write applies to catalog agents. A catalog agent's spec carries
`preferred_models` (model slugs) and never a `model_id`, because model instances
are per-workspace; the model is resolved at install.

### A workspace's own skill has a history

A skill authored, uploaded, imported or edited in a workspace is stored the same
way as catalog content: an immutable package under the sha256 of its files, in
the workspace's own prefix, `skills/<workspace>/packages/<digest>/`. An edit
never rewrites a package; it stores a new one and moves the skill's pointer.
Every move is a row of the skill's history, with its reason (`create`, `edit`,
`install`, `update`, `rollback` or `migrate`), who made it and when.
`GET /v1/workspaces/{workspace}/skills/{skill_id}/versions` lists it, oldest
first, the current one marked. `POST .../versions/{version_id}/rollback` points
the skill at that version's package again; the rollback is itself a new row, so
it can be undone the same way. A move locks the skill's row and writes the
pointer and its history row together, so concurrent edits are ordered and the
history ends where the pointer is; a run already started keeps reading the
package it was configured with. Rolling an edited install back to the version it
was installed at re-pins it to that catalog version, after the same policy check
an install makes, and it reads as not customized again.

### Policy decides where installs may come from

Two policy targets govern installs: `registry:<id>` for one registry, and
`registry_trust:<level>` for every registry of that trust level. Both take
`allow` or `deny` and bind to the workspace or to a user. In each layer a deny
wins, and once a layer has any allow rule it admits only what an allow names.
With no rules, every install is allowed, as with every other policy decision.

A skill imported straight from a GitHub URL passes through no registry. Install
rules name it as the pseudo-registry `registry:github`, with trust `community`,
so `deny registry_trust:community` refuses direct imports too.

The check runs everywhere a catalog item becomes a workspace's own: install,
attaching a catalog skill to an agent, editing a catalog item (which forks it),
updating an installed skill, and a direct GitHub import. It also runs when a task
uses a catalog skill or agent that the workspace never installed. A refusal
answers `403` through the API and fails the task as non-retryable.

### Changing a live registry's mode

Changing `mode`, `source_type`, `source_url`, `source_ref` or `source_path`
clears the stored ETag, so the next sync reads the source in full. For a
platform registry the reconcile applies such a change from the chart values. Going from `upstream` to
`mirror`, that sync stores every item's package. Going from `mirror` to
`upstream`, nothing is deleted: the packages stay in object storage, installed
skills keep pointing at theirs, and an install of a version that was already
stored reuses it instead of fetching.

### Other types still materialize at sync

`skills`, `agents`, `bundles` and `source_types` are catalog-only: a sync writes
the item and nothing else. `mcp_servers` creates an MCP server spec, and
`llm_providers` and `llm_models` upsert provider and model specs. For those
types a changed version sets `update_available` on the item, and the platform
applies it with `POST /v1/workspaces/{workspace}/registries/catalog/items/{item_id}/update`
or `POST /v1/workspaces/{workspace}/registries/{registry_id}/update-all`. Both
are reserved to the platform workspace.

## Why not one global catalog with bodies in the rows

The previous design was exactly that, and measured on a production deployment it
went wrong in every direction the problem section names. The catalog table grew
past a gigabyte, 94% of it rows the source no longer published but that sync
never deleted. Installed community skills were stubs, because the index carried
no body. A customer could not add a private source, because only the platform
could write the catalog.

Splitting the index (small, published whole, replaced on sync) from the content
(immutable, addressed by digest, fetched once) and from the install (a pinned
reference) is what npm, OCI registries, the MCP Registry and Claude Code plugin
marketplaces converge on. The cost is a second store to run: a skill cannot be
installed or run on a deployment without object storage, and a `mirror` sync
needs the storage credentials.

## Why not copy every item into each workspace

Seeding each tenant with every built-in turns each upstream change into N row
migrations. It makes an untouched copy indistinguishable from an edited one. It
replays every deletion per workspace. Reference-and-instantiate (Docker images,
AMIs, GitHub templates, Backstage templates) avoids all three. Provenance is a
link instead: an installed skill, agent or MCP server records `registry_item_id`.

## Limits

- **Trust is a label, not a review.** Nothing scans a registry's content. A
  `verified` registry is one the operator marked so; there is no signature check
  on an index or a package.
- **Installed copies are not re-checked against policy at run time.** A new deny
  rule stops further installs, updates and runs of uninstalled catalog items. A
  skill installed before the rule keeps running until someone removes it.
- **A pointer without a tree SHA is not pinned by the index.** Its catalog card
  and previews read the folder at the branch head, cached per process for an
  hour. An install is pinned, and its updates are found by the sync's check
  above, not by the index; past the 50-a-sync budget they wait for a later sync.
  Installs made before installs recorded the fetched tree hold the version
  `latest`, so they show "update available" once; updating pins them.
- **A token-free read is the archive, not the tree.** A repository whose
  `.gitattributes` uses `export-ignore` or `export-subst`, or a folder holding a
  submodule, archives differently from its git tree: the computed tree SHA then
  differs and a pointer that names one is refused. An archive over 25 MB
  compressed is refused too. Give such a registry credentials.
- **An inline body stays in the catalog row.** An index that publishes `content`
  instead of a pointer has that body stored in the item's spec, in addition to
  the package built from it.
- **Packages are never deleted.** Deleting a skill or rolling it forward keeps
  every package its history names, and a package can be shared by any skill with
  the same files. Nothing yet removes a package no skill or history row points at.
- **The history has no UI yet.** Versions and rollback are API calls only.
- **Version comparison is string inequality.** Any different version, a
  downgrade included, sets "update available".
- **Skills stored before packages are moved lazily.** A row that still holds its
  body in `skills.content`, or that points at the mutable copy a workspace skill
  used to be rewritten in (`skills/<workspace>/<skill id>/`), is moved into a
  package the first time it is read, which starts its history. `agentarea-api
  skills move-bodies-to-packages` and `move-own-copies-to-packages` do it for
  every row at once. The old copies stay until `agentarea-api skills
  delete-moved-own-copies`, which deletes only copies moved at least
  `--min-age-hours` ago (default 168; `--dry-run` counts first). Run it once
  every pod runs this release and no task started before the move is still
  running: such a run reads the copy it was configured with.
- **Nothing in the chart schedules a sync.** See
  [configure the platform registries](/self-host/catalog-registries).

## Related

<Columns cols={2}>
  <Card title="Add a skill registry" icon="robot" href="/guides/agents/add-a-skill-registry">
    Add a GitHub repo or index URL to a workspace and govern installs
  </Card>
  <Card title="Configure the platform registries" icon="server" href="/self-host/catalog-registries">
    The registries every workspace sees, set in the chart values
  </Card>
  <Card title="Skills" icon="robot" href="/concepts/agents/skills">
    How an installed skill reaches the model and the sandbox
  </Card>
  <Card title="Bundles" icon="plug" href="/concepts/integration/bundles">
    The format a catalog `bundles` item holds
  </Card>
</Columns>
