---
title: Bundles
type: concept
summary: A bundle is one portable document describing a working setup — MCP servers, skills, agents, channels, automations, and policies — that is previewed before it is installed.
prerequisites:
  - /concepts/integration/mcp
related:
  - /concepts/integration/registry-and-catalog
  - /concepts/agents/skills
  - /concepts/governance/policy-engine
last_updated: 2026-07-29
---

# Bundles

A bundle is a single document that describes everything a working setup needs:
the MCP servers, the skills, the agents wired to both, the channels that reach
them, the schedules that run them, the policies that constrain them, and the
values a user has to supply. Installing one turns that document into real
workspace resources.

## The problem

A useful agent is never one object. It is an agent plus two MCP instances plus
three skills plus a cron trigger plus a spend cap — and the agent references the
MCP instances by id, and the trigger references the agent by id, and every id is
workspace-local.

Sharing that setup by writing instructions produces a twenty-step guide where
step fourteen silently depends on step three. Sharing it as a database export
produces something that cannot be installed anywhere else, because every
reference is a UUID that means nothing in another workspace. And in both cases
the person installing it finds out what credentials it needs by hitting an error
part-way through, after resources have already been created.

## How AgentArea approaches it

### One fully-inlined document, referenced by key

Schema version `0.1.0`. Every entity has a `key` — a stable in-document
identifier matching `[a-zA-Z][a-zA-Z0-9_]*` — and entities reference each other
by key, never by database id. An agent lists `mcps: [github]` and `skills:
[triage]`; an automation names `agent: triage_bot`. The installer resolves keys
to real ids at install time, which is what makes the document portable.

| Section | Becomes |
|---|---|
| `setup` | The form the user fills in. The only place user-supplied values enter. |
| `mcps` | An MCP server spec plus a configured instance |
| `skills` | A skill, from inline content or a GitHub URL |
| `agents` | An agent with its instruction, model, MCP tools, and skills |
| `channels` | An inbound trigger so messages reach an agent and replies come back |
| `automations` | A cron trigger that runs an agent on a schedule |
| `policies` | Governance rules bound to the workspace or to one of the bundle's agents |
| `metadata` | Listing presentation: developer, category, capabilities, icon, links |

### Secrets never appear in the document

A `SetupField` declares a key, a label, a type, and whether it is required.
Everything else in the bundle references it as `${setup.<key>}`:

```yaml
setup:
  - key: github_token
    label: GitHub personal access token
    type: secret
    required: true

mcps:
  - key: github
    name: GitHub
    json_spec: { type: url, endpoint_url: https://api.githubcopilot.com/mcp/ }
    bindings:
      Authorization: "Bearer ${setup.github_token}"
```

The installer marks the resulting `env_schema` entry as a secret based on
`SetupField.type`, rather than relying on the MCP service's name-based
heuristic. The bundle already declared which inputs are credentials, so guessing
from the variable name is unnecessary and less accurate.

### Analyze, then install

`POST /v1/bundles/analyze` parses the source and returns an `ImportPreview` —
every entity tagged `CREATE`, `REUSE`, or `SKIPPED` with a reason, plus a list
of issues. It writes nothing. This is where a missing setup field, an agent
pointing at a nonexistent MCP key, or a command runtime the platform cannot run
is surfaced.

`POST /v1/bundles/install` takes the canonical bundle and the setup values.
Missing required setup blocks the whole install before anything is written.

Analyze accepts exactly one of `source` (pasted text) or `source_url` (fetched
server-side behind an SSRF guard, capped at 5 MB).

### Install order is dependency order

MCPs, then skills, then agents, then channels, then automations, then policies.
Each step returns the key-to-id map the next one needs. An agent whose MCP was
skipped is still created; an automation whose agent was not created is skipped
with that reason recorded, rather than failing the install.

### Idempotency is by name

Every step checks whether the named entity already exists in the workspace. An
MCP instance, skill, agent, or trigger that exists is marked `REUSED` and not
duplicated. Triggers are named `{bundle_name}:{key}` so they are unambiguous
across bundles. An `InstalledBundle` row is upserted by bundle name, recording
the canonical document and the full install result.

Re-running an install is therefore close to a no-op for what already exists.

### Automations and channels install disabled

`enabled` defaults to `false` on both, and the installer explicitly disables a
cron trigger after creating it — trigger creation schedules unconditionally, so
without that step an imported automation would start running before the user had
confirmed its credentials. Connect, verify, then activate.

### Bundles in the catalog

A registry of type `bundles` holds catalog items whose `spec` **is** the bundle
document, keyed by the bundle's `name`. Nothing is materialized on sync; the
bundle is provisioned into a workspace on demand through the same install path.

## Why not a repository or an archive

A directory layout or a tarball is the familiar packaging shape, and it gives up
the property that matters most here: a bundle must be analyzable before anything
is written.

A single inlined document can be pasted into a form, fetched in one request,
diffed in a pull request, reviewed by a human, and previewed against a live
workspace. An archive means fetch, unpack, and then trust — and the fetch itself
becomes an attack surface with a much larger blast radius than a size-capped
text fetch behind an SSRF guard.

## Why not reference resources by id

Ids are workspace-local. A bundle that names them can be exported from the
workspace that built it and installed nowhere else, including back into the same
workspace after those resources were recreated. Keys cost an indirection at
install time and buy portability, which is the entire point of the format.

## Why not install first and report failures after

The preview exists because a half-finished install is worse than a refused one.
An MCP instance created with a credential, orphaned because the agent step then
failed, is a live secret nobody is tracking. Blocking on missing required setup
before the first write, and reporting unsupported entities as `SKIPPED` in a
preview, moves those failures to a point where nothing has been created yet.

## Limits

- **Only canonical YAML or JSON is parsed.** `parse_bundle` loads the document
  and validates it against the `Bundle` schema. There is no adapter that
  converts a Claude plugin manifest, a repository layout, or any other external
  format — despite what the format module's own docstring implies.
- **Install is not transactional.** The steps run in order and a failure part-way
  through does not undo what earlier steps created. Existence-by-name makes a
  re-run mostly idempotent, which is the mitigation, not a rollback.
- **Command MCPs are restricted to eight runtimes.** `npx`, `uvx`, `uv`,
  `python`, `python3`, `node`, `bunx`, `deno`. A command that is a local path or
  references `${CLAUDE_PLUGIN_ROOT}` is skipped with a reason recorded, not
  failed. Docker and URL MCPs are always accepted.
- **Channels are Telegram only** and **automations are cron only** in `0.1.0`.
  The schema is a closed literal in both cases, so anything else fails
  validation.
- **Skills support inline content and GitHub only.** Zip and S3 import are not in
  `0.1.0`.
- **There is no uninstall.** `InstalledBundle` records what was installed, and
  removing those resources is manual. The API surface is analyze and install.
- **Reuse is by name, not by identity.** An existing agent named `Triage Bot` is
  reused whether or not it came from this bundle, and its configuration is not
  reconciled against the document.
- **`extra="forbid"` everywhere.** An unrecognized field anywhere in the document
  is a validation error, not a warning. A bundle authored against a newer schema
  version is rejected outright rather than partially understood.

## Related

- [Registry and catalog](/concepts/integration/registry-and-catalog) — how a
  bundle reaches a workspace as a catalog item.
- [MCP](/concepts/integration/mcp) — what the `mcps` section provisions.
