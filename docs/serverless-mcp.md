---
title: "Serverless MCP instances"
description: "Start MCP servers on first use and reclaim them once idle, instead of running every connected server continuously."
---

By default, connecting an MCP server starts its container and leaves it running
until someone deletes the connection. A workspace with thirty connections runs
thirty containers, whether or not an agent has called any of them this month.

Serverless mode changes that: a container-backed instance is started on its
first call and stopped again once it has gone idle. The connection, its
credentials, and its discovered tools all stay exactly as they were — only the
running workload comes and goes.

## What changes when you enable it

Two things become visible to users, and both are inherent to the model rather
than defects to work around.

**The first call after an idle period pays a cold start.** How long depends
entirely on the server: a small published image starts in a second or two, while
a `uvx`/`npx` server that clones and installs on boot can take a minute or more.
The call waits for provisioning rather than failing.

**Creating a connection no longer verifies it immediately.** Verification is
what starts the container and lists its tools, so deferring the start defers the
check. A bad image reference or a missing environment variable surfaces on first
use instead of in the connection form.

If neither trade is acceptable for your users, leave it off. It is off by
default.

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

One switch drives every component that has to agree about it — the API and the
worker (which create instances and dispatch tool calls) and the MCP manager
(which reclaims them). Configuring them separately is not possible by design: an
idle timeout without lazy start reclaims nothing, and lazy start without a
timeout brings instances up on demand and then leaves them up forever.

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
family. One box is enough to start:

```bash
cd deploy/sandbox-host
cp inventory.example.ini inventory.ini      # put the host's address in
ansible-playbook -i inventory.ini site.yml \
  -e sandbox_k3s_enabled=true \
  -e sandbox_activation_auth_secret="$SANDBOX_ACTIVATION_AUTH_SECRET"
```

This installs k3s, registers `runsc` with containerd, and creates the `gvisor`
RuntimeClass. It refuses to finish unless a pod really ran under gVisor, so a
green run means the substrate works. It leaves a kubeconfig at
`./execution-cluster.kubeconfig` with the API address rewritten to something
reachable.

**2. Point the control plane at it.**

```
BACKEND_TYPE=kubernetes
KUBERNETES_KUBECONFIG=/path/to/execution-cluster.kubeconfig
KUBERNETES_RUNTIME_CLASS=gvisor
```

`KUBERNETES_KUBECONFIG` beats in-cluster credentials, so a control plane running
inside its own cluster still schedules onto this one. An unloadable file, or an
unrecognised `BACKEND_TYPE`, stops the manager rather than silently using
whatever is nearest.

On Helm, put the kubeconfig in a Secret and name it. The chart mounts it into
every process that creates workloads and sets `KUBERNETES_KUBECONFIG` to the
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

The MCP proxy records a timestamp when traffic passes through it — it is the
only component that sees MCP calls, since the gateway routes to the container
directly. Writes are throttled to one per instance per minute, so an active
instance does not put the database on the hot path of every tool call.

The manager sweeps on `sweepInterval`. For each instance past its idle window it
stops the workload and marks the instance unprovisioned; the database row, the
credentials, and the tool list are untouched. The next call finds it
unprovisioned and starts it again through the same path that started it the
first time.

Sweeping is serialised with a Postgres advisory lock, so running more than one
manager replica does not mean more than one sweeper. If a manager dies
mid-sweep, its lock is released with its connection — there is nothing to clear
by hand.

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

```
MCP idle reaper disabled by explicit zero timeout
```

## Turning it off

Set `serverless.enabled: false`. Nothing is reclaimed any more: an instance that
is currently dormant starts on its next call and then stays up, and one that is
already running keeps running. No connection has to be recreated — the setting
governs reclamation, not how an instance was created.
