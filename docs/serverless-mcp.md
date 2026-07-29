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
by hand.

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
