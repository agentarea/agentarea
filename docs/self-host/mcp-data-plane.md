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

## Bring up the host

Provision the machine with the `sandbox_host` role. It installs Docker, gVisor
(`runsc`), the egress firewall, and the data plane behind TLS:

```bash
cd deploy/sandbox-host
cp inventory.example.ini inventory.ini      # put the host's address in

export MCP_DP_TOKEN=$(openssl rand -hex 24)

ansible-playbook -i inventory.ini site.yml --tags mcp-dataplane \
  -e sandbox_mcp_dataplane_enabled=true \
  -e sandbox_mcp_dataplane_public_hostname=mcp-dp.203-0-113-10.sslip.io \
  -e sandbox_mcp_dataplane_auth_token="$MCP_DP_TOKEN"
```

The play refuses to finish unless the data plane answers `/healthz` **and**
rejects an unauthenticated call with 401. A green run means the process is up and
the door is shut.

The token has no default and no development bypass. A data plane reachable
without one hands container creation on a gVisor host to whoever finds the port.

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
