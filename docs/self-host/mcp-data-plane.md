---
title: "MCP on a dedicated host"
description: "Run MCP servers on a machine of your own, isolated under gVisor, while the control plane keeps its database and secrets elsewhere."
---

MCP servers are third-party code. By default they run wherever the control plane
can reach a container runtime — usually beside the control plane, on its kernel.
A data plane moves them: a machine you own runs the containers, and the control
plane keeps the database, secrets and policy where they already are.

The machine runs the **same image** as the control plane, started in a mode that
builds only a container backend. It never holds a database credential, a Redis
URL or a secret-manager key. Losing that host loses container control on it and
nothing else.

It can also only touch instances it created: every one is stamped with the data
plane's id, and anything without that stamp answers "not found" — to reads,
deletes and health checks alike. A host shared with other workloads cannot be
levered through this API.

## When you want this

- MCP images come from users, and you would rather they never share a kernel
  with your control plane.
- You want gVisor isolation without running a second Kubernetes cluster.
- Your control plane is on managed Kubernetes, where registering a custom
  container runtime is not possible.

If none of those apply, the in-cluster backend is simpler and already the
default.

## What the host must provide

AgentArea does not provision this machine. Build it however you build machines;
what matters is the state it ends up in.

- **Docker**, with **gVisor** (`runsc`) registered as a runtime. This is the
  point of the host: MCP servers are other people's code, and `runsc` is the
  kernel boundary around it.
- **The data-plane binary.** It is `mcp-manager` run in data-plane mode — build
  `./cmd/mcp-manager` from this repository for the host's architecture and
  install it as a service.
- **`MCP_DATAPLANE_AUTH_TOKEN`**, at least 32 characters, the same value the
  control plane will send. There is no default and no development bypass: a data
  plane reachable without a token hands container creation on a gVisor host to
  whoever finds the port.
- **A closed inbound door.** Only the control plane's addresses may reach the
  data-plane port. If the host is published on the internet, terminate TLS in
  front of it and keep the process itself on loopback.
- **Working DNS inside containers.** Containers do not share the host's resolver:
  a stub on `127.0.0.53` is unreachable from them, and Docker then falls back to
  public resolvers the network may not carry. Publish the stub on the Docker
  bridge, or set `dns` in `daemon.json`.

Two checks tell you the host is ready, and they are worth running as part of
whatever builds it:

```bash
curl -fsS http://127.0.0.1:8090/healthz                       # answers 200
curl -so /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8090/dataplane/v1/instances                # answers 401
```

The first proves the process is up; the second proves the door is shut. A host
that passes only the first is an open gVisor host.

## Point the control plane at it

Store the same token in a Secret, then name the host:

```bash
kubectl create secret generic mcp-dataplane-token \
  --from-literal=token="$MCP_DP_TOKEN" -n agentarea
```

```yaml
mcpManager:
  dataPlane:
    url: "https://mcp-dp.203-0-113-10.sslip.io"
    tokenSecret: "mcp-dataplane-token"
    tokenKey: "token"
```

Setting `url` switches the backend; you do not set `BACKEND_TYPE` yourself. All
three fields go together — a partial set stops the render rather than quietly
running containers in the cluster after you asked for them elsewhere.

The hostname above is an example. `203.0.113.10` is a documentation address from
RFC 5737 and resolves nowhere — substitute your host's own name or address.

### When the hop is already private

The public TLS name exists because the token travels on the wire. If the control
plane reaches the host over a network that is already private — a cloud provider's
internal network, WireGuard, an SSH tunnel — there is no public name to certify,
and the data plane is addressed directly:

```yaml
mcpManager:
  dataPlane:
    url: "http://10.0.0.10:8090"
```

The manager refuses a plain-`http` data plane unless you also say the hop is
private, so this arrangement cannot happen by accident:

```
MCP_DATAPLANE_ALLOW_INSECURE=true
```

Both topologies are supported, and which one a deployment uses is not visible
from the outside: **a private deployment has no public data-plane hostname at
all**, so probing one tells you nothing. Check `MCP_DATAPLANE_URL` on the manager
for the address actually in use, and reach it from inside the network the manager
sits in — see [Verifying it](#verifying-it).

The manager proves the host is reachable and the token accepted at startup, so a
wrong value fails the rollout instead of surfacing later as a broken tool call.

Pair it with [serverless mode](/serverless-mcp) if you want instances reclaimed
when idle. A call to a reclaimed instance starts it and waits — first for the
container, then for the server inside to accept a connection — so the caller
pays a cold start rather than getting an error.

## Connect a client

Instances are reached through the data plane, on one authenticated origin. There
is no port published per instance: the token that gates management gates traffic,
and the data plane strips it before forwarding, so an MCP server never sees your
credential.

```
https://<data-plane-host>/dataplane/v1/instances/<instance-id>/proxy/mcp
```

With Codex:

```bash
export AGENTAREA_MCP_TOKEN="$MCP_DP_TOKEN"

codex mcp add my-server \
  --url https://mcp-dp.203-0-113-10.sslip.io/dataplane/v1/instances/<instance-id>/proxy/mcp \
  --bearer-token-env-var AGENTAREA_MCP_TOKEN
```

The token is read from the environment rather than written into the config file.
Any client that speaks MCP Streamable HTTP and can send a bearer token works the
same way.

## Verifying it

Run these from where the control plane runs, not from your workstation. A data
plane on a private hop is unreachable from anywhere else by design, and a host
firewalled to one region refuses everyone outside it — in both cases a probe from
a laptop times out on a healthy host. From a control-plane cluster:

```bash
kubectl -n agentarea exec deploy/agentarea-app-backend -- \
  curl -s "$MCP_DATAPLANE_URL/healthz"
```

`/healthz` is the one unauthenticated route; it answers `{"agent_id":"…","status":"ok"}`
and settles whether the process is up before you look at anything else. Take
`$MCP_DATAPLANE_URL` from the manager's own environment rather than from this
page — the address here is an example.

Then exercise the authenticated path:

```bash
curl -sN -X POST \
  "https://<data-plane-host>/dataplane/v1/instances/<instance-id>/proxy/mcp" \
  -H "Authorization: Bearer $MCP_DP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"probe","version":"1"}}}'
```

A working data plane answers `text/event-stream` with a `Mcp-Session-Id` header
and the server's `initialize` result. If the instance was idle, this is also the
call that starts it.

Two failures worth telling apart:

- **404 `instance not found`** — the instance is not this data plane's. Either
  the id is wrong, or it was created by a different data plane; ids are not
  shared between them.
- **502 with a message naming the hop** — the container is up but its server is
  not answering. The body says which side failed rather than leaving you with a
  bare gateway error.

## What stays on the control plane

Everything that decides. The data plane is told what to run and never learns
where the values came from — it receives a fully-resolved spec. Provisioning
policy, idle reclamation, credentials for the MCP servers themselves, and the
record of which instance belongs to which workspace all remain where they were.
