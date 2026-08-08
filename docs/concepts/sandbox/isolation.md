---
title: Isolation
type: concept
summary: How AgentArea confines untrusted workloads, which controls apply on which backend, and — importantly — which parts of the tier model are not yet wired, so a default deployment gets less isolation than the design describes.
prerequisites:
  - /concepts/sandbox/why-a-sandbox
related:
  - /concepts/sandbox/sessions
  - /concepts/sandbox/lifecycle
  - /concepts/sandbox/the-file-model
  - /security
last_updated: 2026-07-29
---

# Isolation

Isolation is the boundary between a workload and everything else — the host
kernel, the control plane, other tasks, and other tenants. AgentArea expresses it
as a tier: a named judgement about how much is known about the code, which
resolves to concrete container settings.

Read the [Limits](#limits) section before making a security decision from this
page. Parts of the model below are implemented but not currently reachable, and
a default deployment applies less isolation than the tier names suggest.

## The problem

Confinement decisions get made in two different places by two different kinds of
people, and conflating them produces systems that are hard to reason about.

Whether an image is trustworthy is a domain fact. Only the platform knows that
*this* MCP server was installed from the catalog while *that* one is an image a
user pasted in, and that an agent's shell command has no provenance at all. That
fact does not change when you move clusters.

How to confine something is an infrastructure fact. Which runtime class exists,
whether the nodes have KVM, which namespace enforces what — all of that changes
with the deployment, while the workload does not.

If the application hardcodes runtime classes, every infrastructure change becomes
a code change. If infrastructure decides trust, it has to infer provenance it
cannot see. The organizing rule the code follows is that the service classifies
and the platform provides.

## How AgentArea approaches it

**Three tiers name what is known about the code.**

| Tier | For | Runtime | Capabilities | Privilege escalation | Process cap |
|---|---|---|---|---|---|
| `trusted` | Images the platform builds and ships | Default | Unchanged | Blocked | None |
| `standard` | Third-party MCP servers from the catalog | Default | Drop `ALL` | Blocked | 512 |
| `untrusted` | User-supplied images and agent-authored programs | `runsc` (gVisor) | Drop `ALL` | Blocked | 256 |

The tiers differ mainly in runtime. Dropping capabilities and blocking privilege
escalation are cheap and break almost nothing, so everything above `trusted` gets
them. The meaningful escalation at `untrusted` is a syscall-interposing runtime:
gVisor's `runsc` handles the workload's syscalls in userspace instead of passing
them to the host kernel, so a kernel vulnerability reachable from an unprivileged
syscall does not reach the host. `runsc` needs no KVM, which is why it is the
portable choice; a deployment with `/dev/kvm` can point the same tier at a
microVM runtime.

**An unknown tier is an error.** Resolving a tier name that is not in the table
fails rather than falling back to a weaker profile, so a typo in a deployment
value stops the workload instead of quietly running third-party code unconfined.

**The tier is resolved once and rendered per backend.** Docker turns it into
`--runtime`, `--cap-drop`, `--security-opt no-new-privileges`, `--pids-limit`,
`--user`, and `--read-only` with tmpfs mounts for writable paths. Kubernetes
turns it into a pod security context. What "untrusted" *means* is defined in one
place so the two backends cannot drift.

**Tightening is one-directional by design.** The operator's cluster-wide runtime
class wins over anything a workload asks for, so a per-workload request cannot
drop a sandbox runtime the cluster enforces. Capabilities merge as a union of the
operator's drops and the tier's, because dropping a capability twice is harmless
and missing one is not.

### What the Kubernetes backend applies regardless of tier

These come from the pod and container security context and do not depend on the
tier model being wired:

- `runAsNonRoot` and an explicit `runAsUser`
- The `RuntimeDefault` seccomp profile, restricting the syscall surface
- `automountServiceAccountToken: false`, so a hostile image has no API server
  token to use. This is set on MCP pods, on the warm pool DaemonSet, and
  explicitly re-set on task sandbox pods.
- Read-only root filesystem when configured, with tmpfs mounts for writable paths
- TCP-only probes, so no image is required to expose an HTTP health path

### The execution cluster is chosen fail-closed

An explicitly configured kubeconfig wins over in-cluster credentials, and failing
to load it is fatal rather than a reason to look elsewhere. The ordering used to
be reversed, which meant a manager running inside the control-plane cluster would
create workloads there even when the operator had pointed it at a separate
execution cluster — untrusted workloads landing next to the control plane with
nothing logged. An empty setting means "use the cluster I am in", which is
discovery rather than a fallback.

## Why not rely on containers alone

Namespaces, cgroups, dropped capabilities, seccomp, and a non-root uid are a
serious boundary, and they are what the `standard` tier provides. For code with
known provenance that is a proportionate answer, and it costs nothing in
compatibility or speed.

The gap is the shared kernel. Every syscall a container makes is serviced by the
host kernel, so a vulnerability reachable from an unprivileged syscall is a full
escape regardless of how many capabilities were dropped. The `untrusted` tier
exists because agent-authored commands are the workload where that bet is worst:
the code is unreviewed, and the text that produced it may have come from an
attacker.

The tradeoff is paid in compatibility and performance. gVisor implements a subset
of Linux, and images relying on `io_uring`, iptables/nftables manipulation, block
device mounts, or arbitrary device files can fail under it in ways that do not
reproduce on `runc`. I/O-heavy workloads are slower. Whether the platform's own
catalog images run cleanly under gVisor has not been established, which is one
reason the tier is not yet applied by default.

## Why not per-workload runtime classes in the API

The obvious alternative is to let the caller name a runtime class when creating a
workload. It is flexible and needs no tier table.

It inverts the trust relationship. A runtime class in a request is the caller
asking for a confinement level, and the caller is the party whose code is being
confined. Making it a request field means the security property is expressed as
string precedence, and string precedence cannot say "mandatory".

There is a concrete instance of this in the current code. `InstanceSpec` carries a
`RuntimeClass` field, and tier resolution assigns it to the resolved isolation
unconditionally — despite a comment stating that neither refinement can weaken
the tier. With no cluster-wide class configured, a caller supplying a weaker
runtime class overrides the one `untrusted` asked for. This is unreachable today
only because nothing sets a tier in the first place; it becomes reachable the
moment tiers start being assigned. The field is a defect rather than a feature.

## Why not a Kubernetes operator or CRD for placement

An operator already exists in the repository, so moving placement into it looks
natural.

It relocates the same imperative decision into different code the platform owns.
The mechanisms that belong to the platform are the ones Kubernetes already
supplies — namespaces, the scheduler, RuntimeClass, and admission control. An
admission policy in the execution cluster rejecting any pod without a confining
runtime protects the cluster against pods submitted directly, bypassing the
manager entirely; an operator that only configures what the manager creates does
not.

## Limits

This section describes the current state of the code, verified 2026-07-29. Where
the implementation does not match the model above, the implementation is what a
deployment actually gets.

**No workload is assigned an isolation tier.** No caller outside tests sets
`InstanceSpec.IsolationTier`. The spec assembled in `internal/api/handlers.go`
omits the field, so resolution always falls to the configured default. That
default is `standard` (`DEFAULT_ISOLATION_TIER`), which is not set in any chart
or compose file. The tier model is implemented and its unit tests pass; nothing
produces the input that would select `untrusted`.

**With default chart values, no runtime class is applied, and nothing reports
it.** `charts/agentarea/values.yaml` ships `mcpManager.runtimeClass: ""`. The
`standard` tier declares no runtime. The resolved runtime class is therefore
empty, and the guard in `internal/backends/kubernetes_resources.go` that assigns
`runtimeClassName` only when non-empty skips it. Pods run on the host's default
runtime, normally `runc`. No error is raised and no log line records that the
stronger boundary was not applied. Agent shell commands — the least trusted
workload on the platform — run with container-level isolation only.

**The Docker path's fail-closed check is unreachable.** `ensureRuntimeAvailable`
is genuinely called before starting a container, and it returns a distinct error
refusing to start "without the requested isolation". It begins by returning early
when the resolved isolation requires no runtime, and requiring a runtime means a
non-empty `Runtime`, which only the `untrusted` tier sets. Because no tier is
assigned, the check never fires. Docker and Kubernetes are both fail-open in
practice today; the asymmetry sometimes described between them does not exist in
a running system.

**The operator-level lever does work, and covers everything at once.** Setting
`mcpManager.runtimeClass` propagates to `KUBERNETES_RUNTIME_CLASS`, where it wins
ahead of tier and spec, and to the warm pool DaemonSet's `runtimeClassName`. Task
sandbox pods are built by deep-copying that template's spec, so they inherit it.
This is a working way to confine workloads today, with one consequence: it is a
single global value that cannot distinguish an image the platform built from an
agent's shell, so it applies to all container workloads or to none.

**The process cap is Docker-only.** `PidsLimit` is rendered as `--pids-limit` on
the Docker path and has no equivalent in the Kubernetes backend, which sets no
pod- or container-level PID limit. On Kubernetes, fork-bomb containment depends
on kubelet configuration outside this chart.

**Isolation tiers do not restrict network egress; NetworkPolicy does, under
conditions.** The tier profiles cover runtime, capabilities, privilege
escalation, process count, filesystem, and uid — not the network. Egress is
handled separately, by NetworkPolicies the chart renders:

- MCP instance pods (`mcpManager.instanceNetworkPolicy`, enabled by default) are
  denied RFC1918 and link-local ranges, which includes the `169.254.169.254`
  cloud metadata endpoint, while keeping DNS and public internet.
- Sandbox pods get a default-deny policy allowing DNS and the object store. A
  second policy allows public egress only when the operator enables
  `sandboxRuntime.allowInternet`, while continuing to exclude the configured
  private and link-local ranges. Task callers cannot override this choice.

Two conditions apply. The sandbox policies are rendered only when the warm pool
is enabled, and `mcpManager.warmPool.enabled` is `false` by default — a
deployment not using the warm pool has no sandbox egress policy. And all of them
require a CNI that enforces NetworkPolicy; on a cluster without enforcement they
are accepted by the API server and do nothing.

**A separate execution cluster is not currently reachable.** Pointing
`KUBERNETES_KUBECONFIG` at another cluster schedules workloads there
successfully, but the addresses used to reach them do not resolve across the
boundary: MCP instance URLs are in-cluster service DNS
(`mcp-<name>.<ns>.svc.cluster.local`), and the sandbox file path dials raw pod
IPs. Instances come up and are unreachable, which presents as a connection error
rather than a configuration error.

**Secrets are written into the workload's namespace.** MCP environment variables,
including credentials, are stored in a Kubernetes Secret in the namespace where
the workload runs. If that namespace is moved onto a dedicated execution host,
those bytes are on that host — it should be treated as a holder of user
credentials.

**The Docker and Compose development path is outside the tier model entirely.**
In the development stack the sandbox is a `sandbox-executor` service rather than
a tiered workload, so the guarantees described here do not apply to it. Do not
infer production isolation behaviour from a local stack.

### What to check in your own deployment

Whether isolation is applied comes down to one value that the repository cannot
tell you:

```bash
kubectl get pods -n <namespace> -o custom-columns=\
NAME:.metadata.name,RUNTIME:.spec.runtimeClassName
```

An empty `RUNTIME` column means the pod is on the host's default runtime with no
syscall interposition.

## Related

- [Why a sandbox](/concepts/sandbox/why-a-sandbox) — the threat this confines
- [Sessions](/concepts/sandbox/sessions) — what lives inside the boundary
- [Lifecycle](/concepts/sandbox/lifecycle) — how long a confined workload lives
- [The file model](/concepts/sandbox/the-file-model) — scoping between tasks
- [Security](/security) — platform-wide security posture
