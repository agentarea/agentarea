---
title: Serverless MCP instances
type: guide
description: "Reclaim idle MCP server workloads and let the next call start them again, instead of running every connected server continuously."
prerequisites:
  - /concepts/integration/mcp
related:
  - /self-host/configuration
  - /self-host/mcp-data-plane
  - /self-host/troubleshooting
  - /concepts/sandbox/lifecycle
last_updated: 2026-09-07
---

Without idle reclaim, a connected MCP server's container runs until someone
deletes the connection. A workspace with thirty connections runs thirty
containers, whether or not an agent has called any of them this month.

Serverless mode reclaims a container-backed instance once it has gone idle, and
the next call starts it again. The connection, its credentials, and its
discovered tools all stay exactly as they were — only the running workload comes
and goes.

It is **on by default** (`mcpManager.serverless.enabled: true`).

<Note>
This setting controls **reclaim only**. On-demand start is not optional: every
container-backed call goes through the manager's demand gateway, which brings a
dormant workload up whether or not reclaim is enabled.
</Note>

## What changes when you enable it

Two things become visible to users, and both are inherent to the model rather
than defects to work around.

**The first call after an idle period pays a cold start.** How long depends
entirely on the server: a small published image starts in a second or two, while
a `uvx`/`npx` server that clones and installs on boot can take a minute or more.
That call waits for provisioning rather than failing.

Calls that arrive while a start is already under way do not queue behind it.
They are answered `503` with a `Retry-After`, and the retry lands on the
workload the first call is bringing up. Queueing them instead would hold a
database connection each for the whole cold start, so a client retrying faster
than a slow start could finish would fill the manager's connection pool — taking
the connection the start itself still needs and stalling every instance, not
only the one being started. A client that honours `Retry-After` sees a slower
first call; one that treats `503` as fatal needs its own retry.

**A reclaimed instance shows no running workload.** The instance row, its
credentials and its tool list are untouched, but nothing is running until the
next call. An operator looking only at pods or containers sees fewer than the
number of connections, and that is the intended state.

Creating a connection still verifies it: `url`-type connections verify
synchronously and block until the check succeeds or fails, while
container-backed ones verify in the background. Reclaim never invalidates that
result — runtime state and verification are separate records.

If the cold-start trade is not acceptable for your users, set
`serverless.enabled: false`.

## Enabling it

```yaml
mcpManager:
  serverless:
    enabled: true
    # How long an instance may go uncalled before it is reclaimed.
    idleTimeout: "10m"
    # How often to look for idle instances.
    sweepInterval: "60s"
```

The switch is read by the MCP manager alone, and it collapses to a single
duration: enabled renders `AGENTAREA_MCP_IDLE_TIMEOUT` as `idleTimeout`, disabled renders
it as `0`, and `0` means "never reclaim". Neither the API nor the worker
configures any of this — they do not decide when a workload starts or stops.

## Bring-up from nothing

The order below is deliberate: each step is independently useful, and the one
genuinely unvalidated question is settled before anything is migrated.

**0. Do your MCP images run under gVisor?** (half an hour, no new infrastructure)

This is the only real unknown. Agent `bash()` under gVisor is already proven by
whatever you run today; your MCP images are not. On any Linux host with `runsc`
installed:

```bash
docker run --rm --runtime=runsc  <your-mcp-image> --help
docker run --rm --runtime=runc   <your-mcp-image> --help   # control
```

Watch for `io_uring`, iptables/nftables, block-device mounts and arbitrary
device files — those are where gVisor's syscall coverage stops. An image that
fails here needs an escape hatch, and it is much cheaper to learn that now.

**1. An execution cluster.** gVisor needs no KVM or nested virtualization, so
any ordinary VM will do — you do not need bare metal or a special instance
family. One box is enough to start. Build it however you build machines; it has
to end up with:

- a Kubernetes distribution the control plane can reach (k3s on a single node is
  plenty),
- `runsc` registered with containerd as a runtime handler,
- a `RuntimeClass` named `gvisor` pointing at that handler,
- a kubeconfig whose API address is reachable from the control plane, which is
  usually not the address the installer writes into it.

Prove the substrate before trusting it — that a `RuntimeClass` exists says
nothing about whether a pod can actually run under it:

```bash
kubectl run gvisor-check --rm -it --restart=Never \
  --overrides='{"spec":{"runtimeClassName":"gvisor"}}' \
  --image=busybox -- dmesg | head -1     # gVisor announces itself here
```

**2. Point the control plane at it.**

```text
AGENTAREA_MCP_BACKEND=kubernetes
AGENTAREA_K8S_KUBECONFIG=/path/to/execution-cluster.kubeconfig
AGENTAREA_K8S_RUNTIME_CLASS=gvisor
```

`AGENTAREA_K8S_KUBECONFIG` beats in-cluster credentials, so a control plane running
inside its own cluster still schedules onto this one. An unloadable file, or an
unrecognised `AGENTAREA_MCP_BACKEND`, stops the manager rather than silently using
whatever is nearest.

On Helm, put the kubeconfig in a Secret and name it. The chart mounts it into
every process that creates workloads and sets `AGENTAREA_K8S_KUBECONFIG` to the
mounted path:

```bash
kubectl create secret generic exec-kubeconfig \
  --from-file=kubeconfig=./execution-cluster.kubeconfig
```

```yaml
mcpManager:
  runtimeClass: gvisor
  executionCluster:
    kubeconfigSecret: exec-kubeconfig
    kubeconfigKey: kubeconfig
```

Name both fields or neither. Naming one alone stops the render, because a
half-configured execution cluster would otherwise deploy as in-cluster mode —
untrusted workloads back on the control plane's nodes, with nothing to say so.

**3. Turn serverless on** with the values above, and confirm with the checks
under *Verifying it works*.

MCP servers can move first and independently — they are plain Deployments.
Agent sandboxes depend on the file API, which now works on Kubernetes but is
worth exercising on a real task before you retire the old executor.

## Which instances are affected

Reclamation is a property of the deployment, not of the instance. Every
container-backed instance is eligible while the setting is on, whenever it was
created; turning the setting off stops reclaiming all of them. Liveness lives in
the control-plane runtime tables rather than on the instance row, so there is no
per-instance serverless flag to inspect.

Excluded from reclamation:

- **Remote (`url`-type) connections** — there is no container to start or stop.
- **Instances that have never been called.** An instance with no runtime row is
  treated as new, not as idle. Reclaiming requires evidence of disuse, not the
  absence of evidence of use.
- **Instances with a live request lease.** A call in flight holds a lease, and a
  leased instance is never swept out from under it.

## How reclaiming works

Every container-backed call passes through the manager's demand gateway, and the
gateway is what records use. On the way in it marks the instance `ready` and
opens a request lease; while the request runs it heartbeats that lease; on the
way out it closes the lease and stamps `last_used_at`. A call in flight is
therefore always visible as a live lease, not inferred from a timestamp that
might be stale.

The manager sweeps on `sweepInterval`. For each instance past its idle window it
stops the workload and marks the instance unprovisioned; the database row, the
credentials, and the tool list are untouched. The next call finds it
unprovisioned and starts it again through the same path that started it the
first time.

Sweeping is serialised with a Postgres advisory lock, so running more than one
manager replica does not mean more than one sweeper. If a manager dies
mid-sweep, its lock is released with its connection — there is nothing to clear
by hand. An instance that began starting between being listed as idle and being
reclaimed holds that lock, so the sweep leaves it and moves on; the next sweep
sees it as it now is.

## Verifying it works

Reclamation is visible in the control plane's runtime table, not in the log. The
reaper is silent while it is working — it logs only when a sweep or an
individual reclaim fails — so an empty log is the expected state, not evidence
that nothing is running.

With serverless on, create a container-backed connection, call a tool on it, and
watch the instance's runtime state:

```sql
SELECT i.name, r.state, r.last_used_at
FROM mcp_runtime_instances r
JOIN mcp_server_instances i ON i.id = r.instance_id;
```

Immediately after a call the row reads `ready`. Leave the connection alone for
longer than `idleTimeout` and the next sweep moves it to `dormant`, at which
point the workload is gone — the Deployment or container no longer exists, while
the instance row, its credentials, and its discovered tool list are untouched.

Calling the same connection again starts it back up and returns the row to
`ready`. Cold starts are bounded by `startupTimeout`; in practice a small image
that is already present comes back in a few seconds.

If a workload is never reclaimed, check that `idleTimeout` is non-zero. A zero
timeout disables the reaper, and that is the one case it announces:

```text
MCP idle reaper disabled by explicit zero timeout
```

## Turning it off

Set `serverless.enabled: false`. Nothing is reclaimed any more: an instance that
is currently dormant starts on its next call and then stays up, and one that is
already running keeps running. No connection has to be recreated — the setting
governs reclamation, not how an instance was created.
