---
title: Connect an MCP server in a private network
type: guide
description: "Reach an MCP server that has no public address through the AgentArea relay: run frpc next to it, then register the tunnel URL."
prerequisites:
  - /guides/mcp/connect-a-remote-server
related:
  - /guides/mcp/connect-a-remote-server
  - /guides/mcp/pass-secrets
  - /guides/mcp/add-a-hosted-server
last_updated: 2026-11-01
---

Do this when the MCP server lives somewhere AgentArea cannot reach: a
Kubernetes cluster, an office network, a VPC with no inbound rules. A small
client, [frpc](https://github.com/fatedier/frp), runs next to the server and
dials **out** to `relay.agentarea.ru` on port 443. The server then answers at
`https://<subdomain>.relay.agentarea.ru`, and AgentArea calls it like any
[remote server](/guides/mcp/connect-a-remote-server). Nothing is opened in your
network.

If the server already has a public URL, skip the relay and connect it directly.

<Warning>
The relay is a pilot. Every client uses one shared relay token, so anyone
holding it could take a subdomain that is not connected at the moment. Each
tunnel is still guarded by its own password, which is checked before any
request reaches your server. Per-workspace tokens are planned.
</Warning>

## Prerequisites

- The relay token. Ask the AgentArea team for it; it is not self-service yet.
- A host or pod next to the MCP server that can open outbound HTTPS to
  `relay.agentarea.ru:443`, with Docker or Kubernetes.
- The server's MCP endpoint as seen from that host, for example
  `http://grafana-mcp:8000/mcp`, and the credential the server itself expects.
  Run the server with its own authentication: the relay forwards whatever
  passes the tunnel password.

## Steps

<Steps titleSize="h3">
  <Step title="Pick a subdomain and a tunnel password">
    The subdomain is global across all relay users, so prefix it with your
    workspace, for example `acme-grafana`. Generate the password:

    ```bash
    openssl rand -hex 32
    ```
  </Step>

  <Step title="Write frpc.toml">
    frpc substitutes `{{ .Envs.NAME }}` from its environment, so no secret
    sits in the file.

    ```toml
    serverAddr = "relay.agentarea.ru"
    serverPort = 443
    loginFailExit = false
    auth.token = "{{ .Envs.FRP_AUTH_TOKEN }}"
    transport.protocol = "wss"
    # Required: without a CA file frpc does not verify the relay's certificate.
    transport.tls.trustedCaFile = "/etc/ssl/certs/ca-certificates.crt"

    [[proxies]]
    name = "acme-grafana"
    type = "http"
    localIP = "grafana-mcp"
    localPort = 8000
    subdomain = "acme-grafana"
    httpUser = "agentarea"
    httpPassword = "{{ .Envs.TUNNEL_PASSWORD }}"
    # The server's own credential. The relay checks the tunnel password, then
    # this header replaces it, so the server token never leaves your network.
    requestHeaders.set.Authorization = "Bearer {{ .Envs.MCP_TOKEN }}"
    ```

    Add `hostHeaderRewrite = "<name>"` when the server only accepts a known
    `Host`. Add one `[[proxies]]` block per server.
  </Step>

  <Step title="Run frpc">
    With Docker:

    ```bash
    docker run -d --name frpc --restart unless-stopped \
      -e FRP_AUTH_TOKEN -e TUNNEL_PASSWORD -e MCP_TOKEN \
      -v "$PWD/frpc.toml:/etc/frp/frpc.toml:ro" \
      fatedier/frpc:v0.71.1 -c /etc/frp/frpc.toml
    ```

    In Kubernetes, run the same image as a one-replica Deployment. Mount
    `frpc.toml` from a ConfigMap, and pass the three values from a Secret as
    environment variables. It needs no Service and no ServiceAccount token.
    Pin the image tag: frp is pre-1.0, and its config format has changed
    between releases.
  </Step>

  <Step title="Register the tunnel in AgentArea">
    Create a URL connection as in [Connect a remote MCP
    server](/guides/mcp/connect-a-remote-server). Use the tunnel URL plus the
    server's own path, and send the tunnel password as Basic auth:

    ```bash
    BASIC="Basic $(printf 'agentarea:%s' "$TUNNEL_PASSWORD" | base64)"
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-server-instances/with-spec" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "server": {
          "name": "Grafana (private)",
          "description": "Grafana MCP through the relay.",
          "remote_url": "https://acme-grafana.relay.agentarea.ru/mcp",
          "version": "1.0.0",
          "env_schema": [
            {"name": "Authorization", "description": "Tunnel Basic auth", "isSecret": true}
          ]
        },
        "instance": {
          "name": "Grafana (private)",
          "json_spec": {
            "type": "url",
            "endpoint_url": "https://acme-grafana.relay.agentarea.ru/mcp",
            "headers": {"Authorization": "'"$BASIC"'"}
          }
        }
      }'
    ```

    Then set which tools agents may call on the connection's **Tools** tab.
  </Step>
</Steps>

## Verify

frpc logs `start proxy success` once per tunnel:

```bash
docker logs frpc 2>&1 | grep -E "login to server success|start proxy success"
```

The tunnel refuses a request without the password and answers one with it:

```bash
URL=https://acme-grafana.relay.agentarea.ru/mcp
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$URL"          # 401
curl -s -X POST "$URL" -u "agentarea:$TUNNEL_PASSWORD" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
```

A JSON-RPC result carrying the server's `serverInfo` means the request crossed
the relay, the tunnel and your server. In AgentArea, the instance's
`verification.status` should be `succeeded`.

## Troubleshooting

<AccordionGroup>
  <Accordion title="`connect to server error: EOF` in the frpc log">
    TLS to `relay.agentarea.ru:443` did not complete. Check that the host can
    open outbound HTTPS, and that `transport.protocol` is `wss`: plain `tcp` on
    port 443 fails this way.
  </Accordion>
  <Accordion title="`start error: router config conflict`">
    Another client holds that subdomain. Pick a different, workspace-prefixed
    subdomain.
  </Accordion>
  <Accordion title="404 from the tunnel URL">
    No frpc is connected for that subdomain right now. Check that frpc is
    running and logged `start proxy success`.
  </Accordion>
  <Accordion title="401 with the right tunnel password">
    The relay accepted the password, and your server rejected the `Bearer` that
    frpc set. Check `MCP_TOKEN`. If the server checks the `Host` header, set
    `hostHeaderRewrite`.
  </Accordion>
</AccordionGroup>

## Related

- [Connect a remote MCP server](/guides/mcp/connect-a-remote-server)
- [Pass secrets to an MCP server](/guides/mcp/pass-secrets)
- [Add a hosted MCP server](/guides/mcp/add-a-hosted-server)
