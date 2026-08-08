---
title: Why a sandbox
type: concept
summary: Agents run code that no human wrote or reviewed, so the platform treats every command an agent produces as hostile input and runs it somewhere it can do bounded damage.
prerequisites:
  - /agentic-networks
related:
  - /concepts/sandbox/isolation
  - /concepts/sandbox/sessions
  - /concepts/sandbox/the-file-model
  - /concepts/governance/tool-authorization
last_updated: 2026-07-29
---

# Why a sandbox

An agent decides at run time what code to run. The model reads a task, writes a
shell command, and something executes it. Nobody reviewed that command, it did
not exist when you deployed the system, and it will be different next time. The
sandbox exists because that command has to run somewhere, and the only safe
assumption about it is that it might be hostile.

This is not a statement about model quality. A model that is working correctly
still produces code shaped by whatever text it was given, and that text arrives
from issue trackers, web pages, uploaded files, and tool output that the platform
does not control.

## The problem

Three kinds of code run on this platform, and the platform authored none of them.

**Commands the model wrote.** The agent's shell tool takes a command body the
model produced and runs it. The isolation table in the manager names this
directly: the untrusted tier is for "code a user supplied — custom MCP servers
and agent-authored programs" (`internal/config/isolation.go`). There is no
provenance to inspect, because the code did not exist until a moment ago.

**MCP server images.** Connecting an MCP server runs a container image. Some
come from a public catalog, some the user supplies by reference. Appearing in a
catalog records that the platform listed an image, not that the platform built or
audited it.

**Whatever those two pull in.** A `uvx` or `npx` MCP server resolves and installs
packages on boot. The agent's shell can install more.

Without isolation, each of these runs with whatever the host process has. The
concrete failures are ordinary, and none of them require an attacker:

- A command reads credentials from the environment or a mounted service account
  token and exfiltrates them. Kubernetes mounts a service account token into
  every pod by default, and that token talks to the API server.
- A fork bomb or a runaway build consumes the node, taking down unrelated
  workloads that happen to share it.
- Task A reads task B's files, because both run under the same uid against the
  same filesystem.
- A container escape through a kernel bug reaches the host, and the host is the
  one running the control plane.

The last one is the reason a syscall boundary matters. Container isolation is
namespaces and cgroups over a shared kernel; a kernel vulnerability reachable
from an unprivileged syscall is a full escape. When the code making the syscall
was written by a model thirty seconds ago in response to attacker-influenced
text, the ordinary container boundary is thinner than the threat.

**Prompt injection makes this a live path, not a theoretical one.** An agent that
reads a web page, an email, or an uploaded document is reading text an attacker
may have written. If that text convinces the model to run a command, the attacker
has reached the shell without touching the platform. Every control that assumes
"the operator decided what runs here" is bypassed, because the operator decided
to run an agent, and the agent decided the rest. This is why the boundary has to
be around execution rather than around deployment.

## How AgentArea approaches it

The platform separates *classifying* a workload from *confining* it.

Classification is a domain judgement about the code: how much is known about
where it came from. The manager expresses this as an isolation tier — `trusted`
for images the platform builds, `standard` for third-party catalog servers, and
`untrusted` for user-supplied images and agent-authored programs. Each tier
resolves to a set of concrete settings: dropped capabilities, blocked privilege
escalation, a process cap, and for `untrusted`, a syscall-interposing container
runtime (gVisor's `runsc`).

Confinement is what the infrastructure does with that judgement — which runtime
class, which node, which cluster. It changes when you change infrastructure,
while the workload does not.

Around execution sit three further boundaries, each covered on its own page:

- **A session per task**, so one task's processes and working directory are not
  another's. See [sessions](/concepts/sandbox/sessions).
- **A file model scoped by workspace and task**, where cross-task object
  references are rejected before a transfer URL is ever signed. See
  [the file model](/concepts/sandbox/the-file-model).
- **A lifecycle that reclaims workloads**, so a compromised sandbox does not
  live indefinitely. See [lifecycle](/concepts/sandbox/lifecycle).

The sandbox is one layer among several. Tool authorization decides whether the
agent may call a tool at all, and it decides that before execution. The sandbox
assumes those decisions can be wrong or bypassed and bounds the damage when they
are.

## Why not run agent code in the application process

It is simpler, faster, and it is what a single-tenant script does. Running the
model's command with `subprocess` in the worker skips provisioning entirely.

It fails on blast radius. The worker holds database credentials, LLM provider
keys, and a connection to the control plane. Code running in that process has all
of it, so a single injected command is a full compromise of the platform rather
than of one task. There is also nothing to reclaim: a runaway process competes
with the worker's own event loop, and the worker is what would have to kill it.

The tradeoff the platform accepts instead is real. Provisioning costs time, a
warm pool exists to hide that cost and adds resident capacity to pay for, files
have to cross a boundary rather than being local, and the whole data plane is
more machinery to operate. That is the price of the blast radius being one task.

## Why not a container per task and stop there

This is the common answer, and it is most of the way there — it is what the
`standard` tier gives you: dropped capabilities, no privilege escalation, a
process cap, a non-root uid, and a seccomp profile.

It stops short on one axis. Containers share the host kernel, so the isolation
holds only as long as the kernel does. For code with known provenance that is a
reasonable bet. For a command a model wrote in response to text an attacker
supplied, the platform's position is that the bet is worse, which is why the
`untrusted` tier adds a syscall-interposing runtime that keeps the workload's
syscalls away from the host kernel.

The cost is compatibility and speed. gVisor implements a subset of Linux, and
images that use `io_uring`, manipulate iptables, or mount block devices can fail
under it in ways that do not reproduce on the default runtime. Syscall
interposition also costs performance on I/O-heavy work.

## Limits

**The isolation tier is not currently set on any workload.** No caller outside
tests assigns `InstanceSpec.IsolationTier`; the spec built in
`internal/api/handlers.go` leaves it empty, so every workload resolves to the
configured default, which is `standard`. The `standard` profile declares no
runtime. The tier model described above is implemented and reachable, but nothing
produces the input that would select `untrusted`.

**With a default chart, no sandbox runtime is applied, and nothing says so.**
`charts/agentarea/values.yaml` ships `mcpManager.runtimeClass: ""`. Combined with
the point above, the resolved runtime class is empty, and the guard in
`internal/backends/kubernetes_resources.go` that only sets `runtimeClassName`
when it is non-empty skips the assignment. Pods land on the host's default
runtime, normally `runc`. There is no error and no log line recording that the
stronger boundary was not applied.

**The operator-level lever does work.** Setting `mcpManager.runtimeClass`
applies that runtime class to MCP instances and to sandbox pods. It is a single
global value rather than a per-workload decision, so it cannot distinguish a
trusted image from an agent's shell — it covers everything or nothing.

**The Docker path's fail-closed check does not fire.** The manager contains a
check that refuses to start a workload when the requested runtime is not
installed. It returns early when the resolved isolation requests no runtime, and
because no caller sets a tier, no workload requests one. The refusal path is
written but unreachable.

See [isolation](/concepts/sandbox/isolation) for what each of these means for a
deployment, and what to verify before relying on the boundary.

**The sandbox does not stop an agent from misusing tools it is allowed to
call.** Isolation bounds what code can do to the host and to other tasks. An
agent that has been granted a tool and uses it to do something unwanted is a
governance question, handled by
[tool authorization](/concepts/governance/tool-authorization) and
[policy](/concepts/governance/policy-engine).

**Network egress is confined by a separate mechanism with its own conditions.**
The isolation tiers cover capabilities, privilege escalation, process count,
filesystem, and container runtime — not the network. Egress is restricted by
Kubernetes NetworkPolicies instead, which block cloud metadata and internal
ranges but are rendered only under certain chart settings and require a CNI that
enforces them. See [isolation](/concepts/sandbox/isolation) for what applies
when.

## Related

- [Isolation](/concepts/sandbox/isolation) — the security boundary and what it
  does not cover
- [Sessions](/concepts/sandbox/sessions) — one sandbox per task, and its lifecycle
- [The file model](/concepts/sandbox/the-file-model) — what an agent may read and write
- [Lifecycle](/concepts/sandbox/lifecycle) — warm pool, activation, and reclaim
- [Tool authorization](/concepts/governance/tool-authorization) — the layer that
  runs before execution
