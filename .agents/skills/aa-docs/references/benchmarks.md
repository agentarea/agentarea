# Benchmarks: what comparable doc sites do

Surveyed 2026-07-29 via `llms.txt`, sitemaps and navigation. Recorded so the
research is not repeated. Re-verify before citing a specific structure — these
sites change.

## Findings that drove the AgentArea structure

1. **Every site separates Reference into its own branch.** The only exception is
   Grafana, where configuration is scattered into feature guides — and that is
   its most-criticised trait. AgentArea currently resembles Grafana.
2. **Nobody names navigation sections after Diataxis genres.** No site ships
   top-level `tutorials/ how-to/ reference/ explanation/`. Sections are named
   after the reader's object (Tailscale: "Manage your tailnet", "Expand your
   tailnet") or their verb (Dagster: Build, Automate, Operate, Observe, Test).
   Diataxis is the discipline, not the label.
3. **Open-core products give operations its own branch** and badge the paid line
   inline. Vault marks `ENT` on every enterprise feature; Supabase splits
   "Manage" from "Build"; Dagster splits "Operate"; Letta has "Self-Hosting".
4. **Agent platforms document governance as a first-class section.** OpenAI
   Agents SDK has "Coordination and Safety"; OpenFGA has an entire "Authorization
   for Agents" branch. AgentArea's differentiator, buried today under "Features".
5. **Sandbox products document the boundary, not just the API.** Vercel Sandbox
   has concept pages for isolation architecture, runtimes, persistence,
   snapshots, drives — separate from the SDK reference and from task-oriented
   guides.
6. **Frontmatter is a contract.** Vercel attaches `type`, `prerequisites`,
   `related`, `summary`, `last_updated` to every page. Machine-checkable
   metadata is metadata that stays true.
7. **Docs are becoming an agent surface.** Stripe ships `stripe-docs` as an
   agent skill; Langfuse ships a docs MCP server and a coding-agent skill;
   better-auth has an "AI Resources" section; nearly everyone serves `llms.txt`.
   AgentArea, being an agent platform, should not be behind its own customers.

## Direct competitors and adjacent platforms

| Site | Structure | Take |
|---|---|---|
| [Inngest](https://www.inngest.com/docs) | Learn / Reference / Examples | Cleanest three-way split surveyed |
| [Modal](https://modal.com/docs) | Guide / Examples / Reference / Playground | Same plus an interactive tier |
| [Trigger.dev](https://trigger.dev/docs) | guides ×80, management API ×69, self-hosting, realtime, config | Closest peer: Mintlify, durable execution, self-hostable |
| [E2B](https://e2b.dev/docs) | api-reference ×65, sandbox, template, agents, code-interpreting, volumes, network, mcp | Reference organised by sandbox entity |
| [Vercel Sandbox](https://vercel.com/docs/sandbox) | Quickstart / Working with Sandbox / Concepts / Multi-Agent / JS+Python SDK / CLI / Pricing | **The model for AgentArea's sandbox docs** |
| [Temporal](https://docs.temporal.io) | Core Primitives / Concepts / SDK Guides / Production Deployment | Primitives split out from concepts |
| [Letta](https://docs.letta.com) | Getting Started / Core Concepts / Using Your Agent / Channels / Computers / Self-Hosting / SDK | Direct competitor, explicit self-hosting branch |
| [Cloudflare Agents](https://developers.cloudflare.com/agents/) | Overview / concepts / getting-started / runtime / platform / Tools / Harnesses / MCP / communication-channels / examples | Best agent-platform IA surveyed |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | Start Here / Core Concepts / **Coordination and Safety** / Operations and Configuration / Observability and Tracing / Modalities / API Reference | Safety as a named section |
| [Google ADK](https://google.github.io/adk-docs/) | Build Agents / Run Agents / Components / Reference | Verb-named sections |
| [Mastra](https://mastra.ai/docs) | Docs / Models / Guides / Reference | — |
| [LangGraph](https://docs.langchain.com) | overview, concepts, how-tos, reference | Sprawling; not a model to copy |
| [CrewAI](https://docs.crewai.com), [Restate](https://docs.restate.dev), [Daytona](https://docs.daytona.io), [Prefect](https://docs.prefect.io), [Resend](https://resend.com/docs) | Mintlify, flat | Same platform as AgentArea, same flatness problem |
| [Composio](https://docs.composio.dev) | Get Started / Customizing sessions / Authenticate users / Triggers / Security and Data / API Reference / Toolkits | Auth and security surfaced early |

## Open-core and self-hosted peers

| Site | Structure | Take |
|---|---|---|
| [HashiCorp Vault](https://developer.hashicorp.com/vault/docs) | About / Key concepts + OPERATIONS + CLI/APIs, `ENT` badges | **Model for the open-core line** |
| [Supabase](https://supabase.com/docs) | Start / Products / Build / Manage / Reference / Resources | Manage separated from Build |
| [Dagster](https://docs.dagster.io) | Getting Started / Tutorial / Build / Automate / Operate / Observe / Test | Verb-named, operations first-class |
| [Grafana](https://grafana.com/docs/grafana/latest/) | Set up / Administration / Troubleshooting / Upgrade | **Antipattern**: no reference branch |
| [Airbyte](https://docs.airbyte.com), [PostHog](https://posthog.com/docs) | platform / integrations / developers | Flat tool catalogue |
| [Langfuse](https://langfuse.com/docs) | Docs / Integrations / Self-Hosting + docs MCP server + agent skill | Docs-as-agent-surface |

## Authorization and identity

| Site | Structure | Take |
|---|---|---|
| [OpenFGA](https://openfga.dev/docs) | What is OpenFGA / **Authorization Concepts** / **OpenFGA Concepts** / Configuration Language / Getting Started / Modeling Guides / **Authorization for Agents** / Interacting with the API / Best Practices / Industries / Use Cases | **The split to copy**: domain concepts before product concepts. "Authorization for Agents" covers agents as principals, RAG authorization, MCP server authorization, task-based authorization |
| [better-auth](https://www.better-auth.com/docs) | Get Started / Concepts / Guides / AI Resources / Reference | Textbook Diataxis, plus an LLM branch |
| [Clerk](https://clerk.com/docs) | Quickstarts / UI Components / SDK Reference / Beyond the Basics / Learn the Concepts | Concepts pulled out of the fast path |

## General IA references

| Site | Structure | Take |
|---|---|---|
| [Stripe](https://docs.stripe.com) | Use-case first, products by business function, agent skills | Entry through the job, not the product |
| [Tailscale](https://tailscale.com/kb) | Get Started / Manage your tailnet / Expand your tailnet / Resources and reference | **Closest analogy for the VPC narrative** |
| [Cloudflare Workers](https://developers.cloudflare.com/workers/) | get-started / tutorials / examples / Runtime APIs / Configuration / Observability / Glossary | Glossary as a first-class page |
| [Neon](https://neon.com/docs), [Vercel](https://vercel.com/docs) | Product areas + separate Reference | — |
