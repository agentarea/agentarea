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
That call waits for provisioning rather than failing.

Calls that arrive while a start is already under way do not queue behind it.
They are answered `503` with a `Retry-After`, and the retry lands on the
workload the first call is bringing up. Queueing them instead would hold a
database connection each for the whole cold start, so a client retrying faster
than a slow start could finish would fill the manager's connection pool — taking
the connection the start itself still needs and stalling every instance, not
just the one being started. A client that honours `Retry-After` sees a slower
first call; one that treats `503` as fatal needs its own retry.

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

Only instances **created while serverless is on**. The choice is recorded on
each instance when it is created, so enabling the setting later does not
retroactively shorten the life of connections that already exist, and turning it
off does not strand the ones that were created serverless.

Also excluded:

- **Remote (`url`-type) connections** — there is no container to start or stop.
- **Instances that have never been called.** An instance with no recorded use is
  treated as new, not as idle. Reclaiming requires evidence of disuse, not the
  absence of evidence of use.

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
by hand. An instance that began starting between being listed as idle and being
reclaimed holds that lock, so the sweep leaves it and moves on; the next sweep
sees it as it now is.

## Verifying it works

With serverless on, create a container-backed connection and watch the manager:

```bash
kubectl logs -l app.kubernetes.io/component=mcp-manager -f | grep -i idle
```

On startup you should see the reaper announce its window:

```
Starting MCP idle reaper idle_timeout=10m interval=1m0s
```

Call a tool on the connection, leave it alone for longer than `idleTimeout`, and
the sweep reports the reclamation:

```
Stopped idle MCP instance instance_id=... instance_name=...
```

Calling the same connection again starts it back up. If instead you see nothing
at all, the most likely cause is that the instances predate the setting — check
one:

```sql
SELECT name, json_spec->>'lazy_provisioning' AS serverless
FROM mcp_server_instances;
```

Instances showing `false` or an empty value were created eagerly and are never
reclaimed. Recreate the connection to make it serverless.

## Turning it off

Set `serverless.enabled: false`. Instances already created serverless keep that
property, but nothing reclaims them any more: each one starts on its next call
and then stays up. To make them permanently resident, recreate the connections
with the setting off.
