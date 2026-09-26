<div align="center">

![AgentArea](images/agentarea-cover.jpg)

# Run AI agents that act for other people, under rules you can prove.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE.md)
[![CI](https://github.com/agentarea/agentarea/actions/workflows/ci.yml/badge.svg)](https://github.com/agentarea/agentarea/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-docs.agentarea.ai-green.svg)](https://docs.agentarea.ai)
[![Discord](https://img.shields.io/discord/1375237948982821005?color=5865F2&label=discord&logo=discord&logoColor=white)](https://discord.gg/5tduPwheYQ)

[Quickstart](#quickstart) · [How a run works](#what-happens-when-an-agent-runs) · [Architecture](#architecture) · [Docs](https://docs.agentarea.ai) · [Discord](https://discord.gg/5tduPwheYQ)

</div>

AgentArea is a self-hosted platform for running AI agents. Each run is a durable
Temporal workflow. Before any model call or tool call executes, it passes a
policy gate that can allow it, deny it, or park the run until a named person
approves. Tools are reached through MCP servers and through sandboxes from a
provider you choose. Credentials are resolved on the server, so the model never
holds them. Every decision is written down.

**Frameworks give you the agent loop. AgentArea is where that loop runs once
other people depend on it.**

| | Step | What you do |
|---|---|---|
| **01** | Connect | Add model providers, MCP servers and skills from the catalog, plus the secrets they need. |
| **02** | Define | Create agents with instructions, a model and tools. Set the rules: which tools are denied, which need approval, what a workspace or a single task may spend. |
| **03** | Run and supervise | Start tasks from the dashboard, the API, a schedule, a webhook or a chat message. Approve what the rules escalate. Read what happened. |

## AgentArea is right for you if

- Your agents call tools that **change things**: send mail, move money, write to production, open pull requests.
- **Someone other than the agent's author** has to be able to say "not without asking me first".
- Runs take **minutes or hours**, and a deploy or a crash must not lose them.
- You need to answer **"who allowed this, and when?"** after the fact.
- Several people or teams share agents, MCP servers and skills, and **must not see each other's**.
- You want **Claude Code, Codex or Cursor** to reach your company's MCP servers through one governed endpoint instead of each laptop's config.

If you run one agent for yourself, you do not need this. Use Claude Code.

## Problems it solves

| Without AgentArea | With AgentArea |
|---|---|
| The agent process holds your API keys, and model output runs next to them. | Secrets are resolved server-side when a tool is called. Shell commands run in a sandbox, not in the agent's process. |
| "Ask a human first" is a Slack ping and a thread blocked on an HTTP call. | Approval is a workflow state. The run suspends, holds no connection, survives restarts and resumes on a signal. |
| A runaway loop spends the month's budget before anyone looks. | Spend and token caps are checked before each model call. The workspace has a monthly cap; each task has its own. |
| A deploy kills every agent that was mid-task. | Temporal replays the workflow history on another worker. Finished model and tool calls are not repeated. |
| Everyone wires MCP servers into their own editor, with their own tokens. | Register a server once, grant it to a client, and that client gets one MCP endpoint with the workspace's policy applied. |
| Access control is "whoever has the admin password". | Access is a relationship graph (OpenFGA or Ory Keto): this user manages this project, this project contains this agent. Checks fail closed. |

## What happens when an agent runs

An example: a support agent is started by a Stripe webhook about a disputed
charge. It looks up the customer, runs an analysis script, and decides to
refund.

1. **The trigger creates a task.** The API resolves the effective policy by
   merging the workspace, agent, user and task layers, where a lower layer can
   only tighten a higher one. It snapshots that policy onto the task and checks
   the workspace's monthly cap.
2. **Temporal starts the workflow.** A worker runs the loop: build context, call
   the model, execute the tool calls it returns, and repeat.
3. **Every model call passes the budget gate.** Per-task spend and token caps
   are checked before the call, not after.
4. **`lookup_customer` goes to an MCP server.** The server is hosted by
   AgentArea or connected remotely. Its credentials are resolved at call time,
   and the model sees only the result.
5. **The analysis script goes to a sandbox.** The sandbox comes from the
   configured provider: Docker, Kubernetes, E2B, OpenSandbox or Cube. Logs and
   output land in object storage and come back as a handle, not inline.
6. **`refund_payment` matches an approval rule.** The workflow suspends and an
   `approval.request` appears in the approver's inbox. There is no timeout.
7. **A named approver decides.** They do it from the dashboard or from Claude
   Code over MCP. The signal resumes the workflow and the refund runs, or it is
   refused and the model is told why.
8. **Everything above is an event.** It is persisted to the database, streamed
   live to the dashboard, and kept in the audit log.

## Show me a policy

Rules are data. These two rules deny one tool to one agent, and put another
tool behind a named approver:

```json
[
  { "subject_type": "agent", "subject_id": "3f9c1e42-…", "target": "tool:send_email",    "effect": "deny" },
  { "subject_type": "agent", "subject_id": "3f9c1e42-…", "target": "tool:refund_payment", "effect": "approval",
    "params": { "approvers": ["user:alice@example.com"] } }
]
```

Every new workspace starts with a $500 monthly cap, a $50 per-task cap, a
token ceiling, and prompt-injection and output filters turned on. Change them in
the dashboard or through `/v1/workspaces/{workspace}/policies`. The
[policy reference](https://docs.agentarea.ai/reference/policy-syntax) lists
every effect and says which combinations are enforced today.

## Architecture

```
  Dashboard       REST API · CLI    Triggers            Claude Code · Codex
  web UI          API keys          cron · webhook ·    over MCP
                                    Telegram · email
      │               │                 │                     │
      ▼               ▼                 ▼                     ▼
┌────────────────── CONTROL PLANE  ·  decides and records ───────────────────┐
│                                                                            │
│ Identity          Authorization     Policy              Durable runs       │
│ Kratos · Hydra    OpenFGA or Keto   allow · deny · ask  Temporal           │
│ API keys          (ReBAC graph)     spend + token caps  workflows          │
│                                                                            │
│ Approvals         Audit & events    Catalog             Secrets            │
│ inbox · signals   DB + live stream  skills · MCP ·      resolved           │
│                                     agents              server-side        │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
                                      │  every model call and tool call
                                      │  passes the policy gate first
                                      ▼
┌───────────── DATA PLANE  ·  executes; can run in your network ─────────────┐
│                                                                            │
│ Sandboxes                    MCP servers              Object storage       │
│ Docker · Kubernetes · E2B ·  hosted or remote         artifacts and logs,  │
│ OpenSandbox · Cube           OAuth · pinned versions  referenced by handle │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

Model calls go from the worker straight to your LLM providers: any
OpenAI-compatible endpoint, with your keys.

| Component | What it does |
|---|---|
| **API** (Python, FastAPI) | Authentication, authorization and CRUD. Resolves policy and starts runs. Relays events over SSE. Serves MCP at `/mcp`. |
| **Worker** (Python, Temporal) | Runs the agent loop and the governance gates around each call. |
| **MCP manager** (Go) | Starts and stops sandboxes and hosted MCP servers on Docker or Kubernetes, or hands sandboxes to an external provider. |
| **Event service** (Go) | Runs schedules, polling triggers and chat channels such as Telegram, and submits what they produce as tasks. Webhooks are received by the API. |
| **Dashboard** (Next.js) | The web UI: agents, runs, inbox, policies, budgets, catalog, audit. |
| **Backing services** | PostgreSQL, Valkey, S3-compatible storage, Temporal, OpenFGA or Keto, Ory Kratos and Hydra. |

[How it works](https://docs.agentarea.ai/how-it-works) follows one request
through all of them.

## Quickstart

You need Docker with Docker Compose.

```bash
curl -fsSL https://raw.githubusercontent.com/agentarea/agentarea/main/scripts/install.sh | sh
```

The installer downloads the runtime bundle into `./agentarea`, generates the
credentials the stack needs, and offers to start it. It does not clone the
repository or install anything else. From then on it is plain
`docker compose` in that directory.

Then, at **http://localhost:3000**:

1. Add a model provider key under **Models**.
2. Create an agent and give it a tool.
3. Under **Policies**, set that tool to *requires approval*.
4. Start a task that needs the tool. The run pauses. Approve it in **Inbox**
   and watch it finish.

Full walkthrough: [Quickstart](https://docs.agentarea.ai/quickstart).

**On Kubernetes:**

```bash
helm repo add agentarea https://agentarea.github.io/helm-charts
helm install agentarea agentarea/agentarea --namespace agentarea --create-namespace -f values.yaml
```

See [Self-host](https://docs.agentarea.ai/self-host/requirements) for sizing,
gVisor, networking and upgrades.

## Use it from Claude Code, Codex or Cursor

AgentArea serves MCP itself, on two surfaces.

- **`/mcp` lets you operate the platform.** Create agents, start runs, read
  their events, and resolve approvals from your editor.

  ```bash
  claude mcp add --transport http agentarea http://localhost:8000/mcp \
    --header "Authorization: Bearer $AGENTAREA_TOKEN"
  ```

- **`/mcp/clients/{id}` gives each registered client one endpoint.** Behind it
  sit the MCP servers and skills you attached to that client, and the
  workspace's policy applies to every call.
  [Build a compound MCP →](https://docs.agentarea.ai/guides/mcp/build-a-compound-mcp)

## What AgentArea is not

| | |
|---|---|
| **Not an agent framework.** | It does not tell you how to write the loop. It runs the loop and governs what the loop may do. |
| **Not a workflow builder.** | There is no drag-and-drop pipeline. An agent decides its own steps, and policy decides which steps are allowed. |
| **Not an LLM gateway.** | It governs tool calls and runs, not only model traffic. Point a model provider at your gateway if you have one. |
| **Not a hosted service.** | The documented path is self-hosting. |
| **Not small.** | It is several services, a database, a workflow engine and an authorization server. That is the cost of the guarantees above. |

<details>
<summary><b>AgentArea vs. agent frameworks</b> (LangGraph, Mastra, Agno, CrewAI)</summary>

Frameworks are libraries: you import them and the agent runs inside your
process, with your credentials. That is the right tool for one agent, or for
agent behaviour embedded in an existing service. AgentArea is what you operate
when the agent acts for people who did not write it. You get durable execution,
per-call policy, approvals and audit, at the price of running a platform.
</details>

<details>
<summary><b>AgentArea vs. workflow builders</b> (n8n, Dify)</summary>

Workflow builders are good when you can draw the steps in advance. AgentArea
assumes you cannot: the model picks the next tool, so control has to sit at
every call rather than in the shape of the graph.
</details>

<details>
<summary><b>AgentArea vs. LLM gateways</b> (LiteLLM, Portkey)</summary>

Gateways sit between your code and model providers. They route, retry, cache and
filter model traffic. AgentArea sits one level up: it decides whether a tool may
run, who must approve it, and what a task may spend, and it keeps the run alive
while it waits. The two compose.
</details>

## Status and limitations

AgentArea is pre-1.0. These are known gaps, and the docs name more:

- Policy `condition` fields and `group` subjects are stored but not evaluated yet.
- Sandbox isolation tiers, such as gVisor for untrusted code, exist but are not assigned by default.
- Container egress rules are declared but not enforced in core.
- Parts of the agent network model describe intent and are not enforced yet.

Where the documentation and the code disagree, the code is right and the page
is a bug.

## Open core

Everything needed to run governed agents on your own infrastructure is in this
repository, under Apache 2.0. Commercial features ship as a separately installed
package that plugs into named extension points. It is not a fork.

| In this repository | Commercial package |
|---|---|
| Agent execution, tasks, Temporal workflows | Plan entitlements |
| Sandboxes and MCP hosting | Usage metering and billing |
| ReBAC authorization (OpenFGA or Keto) | Forwarding audit to a SIEM |
| Policies, budgets, approvals, audit in the database | Container egress enforcement |

[Open core](https://docs.agentarea.ai/concepts/open-core) explains where the line
is and why.

## Repository

```
agentarea-platform/      API, Temporal worker, domain libraries (Python)
agentarea-webapp/        Dashboard (Next.js)
agentarea-mcp-manager/   Sandbox and MCP server orchestration (Go)
agentarea-event-service/ Triggers and channels (Go)
agentarea-operator/      Kubernetes operator: catalog sync, LLM provider configs
agentarea-cli/           Terminal client (Node.js)
charts/                  Helm charts
docs/                    Source for docs.agentarea.ai
```

To work on AgentArea itself, clone the repository and run `make up-dev`, which
builds images from your working tree. [CONTRIBUTING.md](CONTRIBUTING.md) covers
the rest.

## Community and license

- [Discord](https://discord.gg/5tduPwheYQ) for questions
- [Issues](https://github.com/agentarea/agentarea/issues) for bugs and feature requests
- [SECURITY.md](SECURITY.md) for reporting vulnerabilities privately
- [Code of Conduct](CODE_OF_CONDUCT.md)

Apache License 2.0. See [LICENSE.md](LICENSE.md).
