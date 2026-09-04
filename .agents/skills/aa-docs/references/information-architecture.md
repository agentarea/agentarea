# AgentArea documentation: information architecture

The target structure. Eight top-level groups in `docs/docs.json`. Every group is
named after the reader's object or job, never after a Diataxis genre.

Legend for genre tags: **T** tutorial · **G** guide · **C** concept · **R** reference

---

## 1. Get started

The only group where mixed genres are acceptable, because the reader does not
yet know what they need. Keep it to five pages — it is a funnel, not a shelf.

| Page | Genre | Notes |
|---|---|---|
| `index` — What is AgentArea | C | Replaces `welcome.md` **and** `platform-overview.md`, which today duplicate each other ~70%. One page, one architecture diagram, one value proposition. |
| `quickstart` — Run the platform | T | `make up-dev` to a working dashboard. Under 10 minutes, zero decisions. |
| `first-agent` — Your first agent | T | Create an agent, give it a model, run one task, read the output. |
| `how-it-works` | C | Control plane vs data plane, the request path, what Temporal is doing. The page that makes the rest of the docs legible. |
| `choose-a-deployment` | C | Local · self-hosted Kubernetes · enterprise hybrid. Sets expectations before someone follows the wrong install guide. |

## 2. Tutorials

Sequential, learning-oriented. Each ends with something that runs. No options,
no "you could also" — a tutorial with branches is a guide wearing a costume.
Order matters; each builds on the last.

| Page | Genre |
|---|---|
| `tutorials/first-agent-in-depth` — Build an agent properly (config, prompt, model) | T |
| `tutorials/add-a-tool` — Give your agent a tool with MCP | T |
| `tutorials/run-code` — Run code in a sandbox | T |
| `tutorials/agent-with-skills` — Attach a skill and watch progressive disclosure | T |
| `tutorials/two-agents` — Two agents working together over A2A | T |
| `tutorials/scheduled-agent` — Trigger an agent on a schedule | T |
| `tutorials/govern-an-agent` — Add an approval and a budget | T |
| `tutorials/ship-a-bundle` — Package agents, MCPs and skills as a bundle | T |

## 3. Guides

Task-oriented. Grouped by object, because that is how someone with a problem
searches. Every title starts with a verb.

### Agents
| Page | Genre |
|---|---|
| `guides/agents/create-and-configure` | G |
| `guides/agents/agent-as-a-folder` — `workspace/`, `sandbox.yaml`, policy floors | G |
| `guides/agents/attach-skills` | G |
| `guides/agents/choose-a-model` | G |
| `guides/agents/configure-provider-failover` | G |
| `guides/agents/version-and-fork` | G |
| `guides/agents/install-from-the-catalog` | G |

### Tasks and execution
| Page | Genre |
|---|---|
| `guides/tasks/start-a-task` — API, CLI, and A2A | G |
| `guides/tasks/attach-files` — presigned upload, checksum, CAS | G |
| `guides/tasks/stream-events` — SSE consumption | G |
| `guides/tasks/retrieve-artifacts` | G |
| `guides/tasks/cancel-and-retry` | G |
| `guides/tasks/debug-a-failed-task` — the page that gets linked from every support thread | G |

### Tools and MCP
| Page | Genre |
|---|---|
| `guides/mcp/add-a-hosted-server` | G |
| `guides/mcp/connect-a-remote-server` | G |
| `guides/mcp/authenticate-with-oauth` | G |
| `guides/mcp/pass-secrets` — `env_schema`, secret-by-default | G |
| `guides/mcp/build-a-compound-mcp` | G |
| `guides/mcp/issue-access-tokens` | G |
| `guides/mcp/scope-to-a-registered-client` — codex, claude harnesses | G |
| `guides/mcp/read-the-activity-log` | G |

### Sandbox
| Page | Genre |
|---|---|
| `guides/sandbox/run-a-command` | G |
| `guides/sandbox/provide-input-files` | G |
| `guides/sandbox/collect-artifacts-and-logs` | G |
| `guides/sandbox/choose-an-image` | G |
| `guides/sandbox/set-limits-and-timeouts` | G |
| `guides/sandbox/control-egress` | G |
| `guides/sandbox/debug-a-session` | G |
| `guides/sandbox/enable-serverless-mcp` — absorbs today's `serverless-mcp.md`, which is already a well-shaped guide | G |

### Governance
| Page | Genre |
|---|---|
| `guides/governance/grant-resource-access` | G |
| `guides/governance/authorize-a-tool-call` — must cover all three enforcement layers | G |
| `guides/governance/require-human-approval` | G |
| `guides/governance/set-a-budget` | G |
| `guides/governance/review-the-audit-trail` | G |
| `guides/governance/model-a-custom-relation` | G |

### Triggers and channels
| Page | Genre |
|---|---|
| `guides/triggers/schedule-an-agent` | G |
| `guides/triggers/trigger-from-a-webhook` | G |
| `guides/triggers/react-to-a-platform-event` | G |
| `guides/triggers/connect-a-channel` | G |

## 4. Concepts

Explanation. The genre AgentArea is thinnest on and needs most, because the
product's differentiators (governance, the network model, the sandbox boundary)
are all conceptual.

Follow OpenFGA's split: general domain concepts first, product-specific concepts
second. A reader who does not know what ReBAC is cannot evaluate your ReBAC.

### Platform
| Page | Genre | Notes |
|---|---|---|
| `concepts/agentic-networks` | C | The VPC analogy, stated once and carried consistently. |
| `concepts/control-and-data-plane` | C | Promote today's orphaned `sandbox-control-data-plane.md`. |
| `concepts/workspaces-projects-resources` | C | The scoping model everything else assumes. |
| `concepts/open-core` | C | What is core, what is enterprise, and why the line is there. |

### Agents
| Page | Genre |
|---|---|
| `concepts/agents/what-is-an-agent` — agent-as-a-folder | C |
| `concepts/agents/skills` — progressive disclosure | C |
| `concepts/agents/a2a` — agent-to-agent communication | C |
| `concepts/agents/context-strategies` — static, hybrid, dynamic | C |

### Execution
| Page | Genre |
|---|---|
| `concepts/execution/tasks` — lifecycle and the three terminal states | C |
| `concepts/execution/durable-execution` — what Temporal buys you | C |
| `concepts/execution/events` — the vocabulary and why consumers stay agnostic | C |
| `concepts/execution/artifacts` — content-addressed storage | C |

### Sandbox
| Page | Genre | Notes |
|---|---|---|
| `concepts/sandbox/why-a-sandbox` | C | The threat model. Untrusted model output is the whole reason. |
| `concepts/sandbox/sessions` | C | One sandbox per task, exec in place. |
| `concepts/sandbox/the-file-model` | C | Three surfaces, one store, scoped by prefix: org / user / task. |
| `concepts/sandbox/isolation` | C | The security boundary, honestly stated — including what it does not protect against. |
| `concepts/sandbox/lifecycle` | C | Warm pool, activation, idle reclaim, serverless mode. |

### Governance
| Page | Genre | Notes |
|---|---|---|
| `concepts/governance/authorization-basics` | C | ACL vs RBAC vs ABAC vs ReBAC. Domain-general, product-free. |
| `concepts/governance/the-agentarea-model` | C | Types, relations, tuples as actually deployed. |
| `concepts/governance/policy-engine` | C | PAP / PDP / PEP and where each lives in the code. |
| `concepts/governance/tool-authorization` | C | The three layers a tool call clears — disclosure, task policy, resource grant. |
| `concepts/governance/approvals` | C | Human-in-the-loop, and where it is enforced. |
| `concepts/governance/budgets-and-quotas` | C |
| `concepts/governance/audit` | C |

### Integration
| Page | Genre |
|---|---|
| `concepts/integration/mcp` — what MCP is and how AgentArea hosts it | C |
| `concepts/integration/registry-and-catalog` | C |
| `concepts/integration/bundles` | C |

## 5. Self-host and operate

Operations gets its own branch, as it does at Vault, Supabase, Dagster and
Grafana. Do not scatter configuration into feature guides — that is the specific
mistake Grafana is criticised for.

| Page | Genre |
|---|---|
| `self-host/requirements` — sizing, prerequisites | R |
| `self-host/docker-compose` | G |
| `self-host/kubernetes` — Helm | G |
| `self-host/configuration` — per service, table-driven | R |
| `self-host/secrets-backends` | G |
| `self-host/database-and-migrations` | G |
| `self-host/networking` | G |
| `self-host/observability` — logs, metrics, traces | G |
| `self-host/backup-and-recovery` | G |
| `self-host/upgrades` | G |
| `self-host/troubleshooting` | G |

## 6. Reference

Every benchmarked site has this branch. AgentArea currently has a single 4 KB
page where Trigger.dev has 69 and E2B has 65.

| Page | Genre | Notes |
|---|---|---|
| `reference/api/*` | R | **DONE 2026-07-29.** Generated from `docs/api-reference/openapi.json` via the `API Endpoints` navigation group (a Mintlify group accepts `openapi`; omit `pages` so all operations generate). The copy is kept in sync by `npm run sync:openapi` and guarded in `schema-check.yml`. Never hand-write endpoint tables — the previous hand-written page had 9 of 11 paths wrong. |
| `reference/cli` | R |
| `reference/sdk` | R | The shared `@agentarea/api-client`. |
| `reference/agent-folder` | R | `sandbox.yaml` schema, every key, every default. |
| `reference/policy-syntax` | R | CEL expressions available in rules. |
| `reference/authorization-model` | R | Type definitions and relations. |
| `reference/events` | R | Event names, payloads, terminal states. |
| `reference/environment-variables` | R | Per service. |
| `reference/limits` | R | Timeouts, sizes, quotas, defaults. |
| `reference/errors` | R | Error codes and what to do about each. |
| `reference/glossary` | R | Modelled on Cloudflare Workers. Cheap to write, disproportionately useful. |

## 7. Enterprise

| Page | Genre |
|---|---|
| `enterprise/overview` — the core/enterprise line | C |
| `enterprise/hybrid-execution` — BYO VPC, plaintext boundaries | C |
| `enterprise/sso` | G |
| `enterprise/compliance` | R |

Mark enterprise-only features inline with a badge everywhere else in the docs,
the way Vault marks `ENT`. Silence about the line is worse than the line.

## 8. Contribute

| Page | Genre |
|---|---|
| `contribute/contributing` | G |
| `contribute/engineering-principles` | C |
| `contribute/versioning` | R |
| `contribute/roadmap` | C |
| `contribute/changelog` | R |

**ADRs are not published, and they do not live in this repository.** They belong
in the wiki, `agentarea-wiki/wiki/decisions/`, which already holds the canonical
decision log. An ADR is a point-in-time record that is never updated, only
superseded; a published site must describe current behaviour, so hosting a
deliberately-unmaintained artifact there guarantees pages that are false today.
This matches Rust RFCs, Kubernetes KEPs, Python PEPs and OpenTelemetry OTEPs,
all of which sit outside the user-facing docs.

Consequence: the OSS repo cannot cite an ADR, because the wiki is a separate
private repo. A `docs/` page that wants to explain a decision states the
reasoning in prose instead — that is what the "Why not X" section of a concept
page is for. The ADR is the raw material; the concept page is the product.

**Scheme** (set by `agentarea-wiki/AGENTS.md`, do not invent a new one):

- `wiki/decisions/ADR-NNNN-kebab-slug.md`, four digits, sequential by ingestion.
  The number is an identifier, not a timeline — the `Date` field carries the
  timeline, which is why a lower-numbered ADR can supersede a higher one.
- Status vocabulary: `Accepted` · `Provisional` · `Open` (plus `Superseded by
  ADR-NNNN`).
- Explicit `Confidence:` label — High / Medium / Low.
- Eight required sections: decision, status, context, rationale, rejected
  alternatives, implications, evidence, open questions.
- Register the page in `wiki/decisions/index.md`, then append to
  `logs/change-log.md` under the current date.
- Unresolved conflicts go to `wiki/unresolved/contradictions.md` — never
  silently pick a side.

---

## Migration map for existing files

| Today | Goes to | Action |
|---|---|---|
| `welcome.md` + `platform-overview.md` | `index` | Merge. Two card-walls become one page. |
| `getting-started.md` | `quickstart` | Split the conceptual half into `how-it-works`. |
| `features.md` | — | Delete. Dissolve into Concepts and Guides. A "Features" page is a sitemap with adjectives. |
| `architecture.md` (18 KB) | `concepts/control-and-data-plane` + `how-it-works` | Split. |
| `agentic-networks.md` | `concepts/agentic-networks` | Move. |
| `agent-governance.md` | `concepts/governance/*` | Split across the governance concepts. |
| `agent-communication.md` | `concepts/agents/a2a` | Move. |
| `building-agents.md` | `guides/agents/*` + `tutorials/first-agent-in-depth` | Split by genre. |
| `skills.md` | `concepts/agents/skills` + `guides/agents/attach-skills` | Split. |
| `skill-sandboxing.md` (18 KB) | `concepts/sandbox/isolation` + guides | Split. |
| `sandbox-control-data-plane.md` | `concepts/control-and-data-plane` | Promote — currently orphaned, not in nav. |
| `serverless-mcp.md` | `guides/sandbox/enable-serverless-mcp` | Move as-is; already correctly shaped. |
| `warm-pool.md` | `concepts/sandbox/lifecycle` | Merge. |
| `mcp-integration.md`, `mcp-oauth.md`, `compound-mcps.md`, `mcp-access-tokens.md` | `guides/mcp/*` + `concepts/integration/mcp` | Split by genre. |
| `event-triggers.md` | `guides/triggers/*` | Split into one page per trigger type. |
| `temporal-workflows.md` | `concepts/execution/durable-execution` | Move. |
| `infrastructure.md` (22 KB), `deployment.md` (22 KB) | `self-host/*` | Split. Overlapping today. |
| `secrets-management.md` (20 KB) | `self-host/secrets-backends` + `reference/environment-variables` | Split. |
| `monitoring.md` (31 KB) | `self-host/observability` + `reference/*` | Split. Largest page in the tree. |
| `security.md` | `concepts/sandbox/isolation` + `concepts/governance/*` | Split. |
| `feature-flags.md` | `reference/environment-variables` | Move. |
| `api-reference.md` (4 KB) | `reference/api/*` | Replace with generated output. |
| `examples.md` | Tutorials | Dissolve. |
| `troubleshooting.md` | `self-host/troubleshooting` + `guides/tasks/debug-a-failed-task` | Split. |
| `engineering-principles.md`, `contributing.md`, `VERSIONING.md`, `community.md`, `roadmap.md`, `changelog.md` | `contribute/*` | Move. |
| `audit-analysis.md` (16 KB) | — | Orphaned, internal. Move out of `docs/`. |
| `mcp-roadmap.md` | — | Orphaned. Fold into `contribute/roadmap` or delete. |
| `changelog.mdx`, `contributing.mdx` | — | Delete. Byte-identical duplicates of the `.md` versions. |
| `adr/` + `decisions/` | `agentarea-wiki/wiki/decisions/` | Move out of the repo entirely — not published, and the wiki owns the decision log. Renumber into the existing `ADR-NNNN` sequence continuing from ADR-0020; this dissolves the collision where both directories independently claim ADR-001/002/003 for different decisions. Two records are already superseded by wiki entries (event architecture by ADR-0018, tool-authz in part by ADR-0019) — record the supersession rather than dropping them. Fix the two wiki→repo links that break (`ADR-0019...md:7`, `architecture/eventing-streaming.md:27`) and the one repo citation, `docs/agent-communication.md:6`, which must become prose. |
| `plans/`, `testing/`, `superpowers/`, `.omc/` | — | Internal working material. Move out of `docs/`. `docs/` should contain exactly what Mintlify publishes and nothing else. |

## Sequencing

1. **Hygiene** — delete the two duplicate `.mdx` files, resolve the three
   orphans, and evict everything Mintlify does not publish from `docs/`:
   `plans/`, `testing/`, `superpowers/`, `.omc/`, and both ADR directories,
   which go to `agentarea-wiki/wiki/decisions/` renumbered into its existing
   sequence. Almost pure deletion and movement, no writing, and it immediately
   shrinks the surface everything else has to work against.
2. **Reference from OpenAPI** — the largest gap and the one a generator closes.
3. **Concepts** — the differentiators. Sandbox and governance first.
4. **Renavigate** — land the eight groups in `docs.json`, with redirects.
5. **Split the monoliths** — the four 20 KB+ pages.
6. **Guides and tutorials** — the long tail, written continuously afterwards.
