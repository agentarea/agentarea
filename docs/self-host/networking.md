---
title: Configure networking and ingress
type: guide
summary: Expose AgentArea over ingress, set the public URLs the platform advertises, and restrict egress from pods running untrusted code.
prerequisites:
  - /self-host/kubernetes
related:
  - /self-host/configuration
  - /self-host/requirements
  - /self-host/kubernetes
  - /self-host/troubleshooting
last_updated: 2026-07-29
---

# Configure networking and ingress

Getting AgentArea onto a hostname takes more than an Ingress resource. Three
separate things have to agree: what the Ingress routes, what URL the backend
advertises for itself, and what URL the browser is redirected to for
authentication. Set only the first and you get a site that loads and cannot log
in.

This guide also covers egress restriction for the pods that run code the
platform did not write — MCP server instances and agent sandboxes — which is a
different problem with a different mechanism.

## Prerequisites

- A Kubernetes install of the chart, see [Kubernetes](/self-host/kubernetes)
- An ingress controller matching the `ingress.className` you intend to set
- DNS records you control for the hostnames below
- For egress restriction: a CNI that enforces NetworkPolicy

## Steps

### 1. Enable ingress for the three public surfaces

The chart renders one Ingress each for the frontend, the backend, and Kratos.
Each is created only when `ingress.enabled` is true **and** that host is
non-empty — so an empty `kratos.host` silently produces no Kratos Ingress, and
login breaks with no error at install time.

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    frontend:
      host: app.example.com
      paths:
        - path: /
          pathType: Prefix
    backend:
      host: api.example.com
      paths:
        - path: /
          pathType: Prefix
    kratos:
      host: auth.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: agentarea-tls
      hosts:
        - app.example.com
        - api.example.com
        - auth.example.com
```

`ingress.annotations` and `ingress.tls` are shared across all three Ingresses.
There is no per-host override.

### 2. Set the URLs the platform advertises

These are separate from routing. They are the URLs baked into responses, and
they must be what a *client* can reach, not what a pod can reach.

```yaml
global:
  api:
    publicUrl: https://api.example.com
  webapp:
    url: https://app.example.com
  storage:
    publicEndpoint: https://s3.example.com

kratos:
  urls:
    public: https://auth.example.com
    publicBrowser: https://auth.example.com
```

| Value | Becomes | Used for |
|---|---|---|
| `global.api.publicUrl` | `API_BASE_URL` | Provider icon URLs, OAuth protected-resource metadata, the MCP `WWW-Authenticate` header |
| `global.storage.publicEndpoint` | `PUBLIC_S3_ENDPOINT` | Signing presigned URLs for browser-direct upload and download |
| `kratos.urls.public` | `ORY_SDK_URL` | Server-side calls from the frontend container to Kratos |
| `kratos.urls.publicBrowser` | `ORY_BROWSER_URL` | Where the browser is redirected for login |

`global.api.publicUrl` has a fallback chain: when empty, the chart derives
`https://<ingress.hosts.backend.host>` if ingress is enabled, otherwise the
internal ClusterIP URL. The derived value assumes `https`. If you terminate TLS
elsewhere and serve plain HTTP, set `publicUrl` explicitly.

`kratos.urls.publicBrowser` defaults to `kratos.urls.public`. Set it separately
only when pods cannot resolve the public domain — a split-horizon DNS setup, or
a Tailscale-style overlay where the in-cluster name and the browser-facing name
differ.

`global.storage.publicEndpoint` is empty by default, and the platform then falls
back to the internal endpoint. That works only when the object store is itself
browser-reachable, which in a cluster it usually is not. Leaving it empty is the
single most common cause of file uploads failing in an otherwise working
install.

### 3. Allow browser uploads through CORS

Presigned uploads go from the browser straight to the object store, bypassing
the API, so the object store needs its own CORS rule. The chart applies one to
the artifacts bucket during bootstrap:

```yaml
global:
  storage:
    cors:
      allowedOrigins:
        - https://app.example.com
```

An empty `allowedOrigins` skips the rule entirely rather than defaulting to
something permissive.

### 4. Set the Kratos cookie domain

```yaml
kratos:
  session:
    cookieDomain: example.com
```

The default is `localhost`. A session cookie scoped to `localhost` is not sent
to `app.example.com`, so login appears to succeed and every subsequent request
is anonymous.

Kratos also has its own CORS allow-list under `kratos.config.serve.public.cors.allowed_origins`,
which ships pointing at `staging-0.agentarea.ai`. Replace it with your origins.

### 5. Route MCP server instances

When `mcpManager.backend` is `kubernetes` and `gateway_api` is in
`mcpManager.features.enabled`, the manager creates an HTTPRoute per MCP server
instance, attached to a Gateway you provide.

```yaml
mcpManager:
  domain: mcp.example.com
  gateway:
    name: envoy-gateway
    namespace: envoy-gateway-system
```

Instances are then reachable at `https://<domain>/mcp/<instance-name>`. The
chart does not install Gateway API CRDs or a Gateway; both must exist already.

### 6. Restrict egress from untrusted pods

MCP server instances run user-supplied images. The chart ships a NetworkPolicy,
on by default, that denies them every cluster-internal and link-local range while
allowing DNS and the public internet.

```yaml
mcpManager:
  instanceNetworkPolicy:
    enabled: true
    dnsNamespace: kube-system
    blockedEgressCIDRs:
      - 10.0.0.0/8
      - 172.16.0.0/12
      - 192.168.0.0/16
      - 169.254.0.0/16
    extraEgress: []
```

The `169.254.0.0/16` entry covers the cloud metadata endpoint at
`169.254.169.254`, which is the concrete thing this policy exists to block,
along with kube-apiserver access and lateral movement to other tenants' instance
pods. Ingress is deliberately left open: inbound is fronted by the Service and
gateway, and cross-pod reachability is already cut by every instance's egress
deny.

Add your cluster's pod and service CIDRs if they fall outside these ranges. Some
providers use `100.64.0.0/10`, which the defaults do not cover.

Two limits worth stating plainly:

- **This is a no-op on a cluster whose CNI does not enforce NetworkPolicy.** The chart cannot detect that, and nothing warns you. The policy object exists, and untrusted pods reach the metadata endpoint anyway.
- **This is not kernel isolation.** Egress rules constrain the network; they do nothing about a container escape. That is what `mcpManager.runtimeClass` is for, and it defaults to `""`.

The policy selects pods by both `app.kubernetes.io/managed-by: mcp-manager` and
`app.kubernetes.io/component: mcp-server`. The component constraint is
deliberate: workflow sandboxes are also manager-created, and locked sandboxes
must not inherit this public-egress allowance. They are governed by
`mcpManager.warmPool.lockedNetworkPolicy` instead, which grants no public egress
at all — add stable S3 endpoint CIDRs to `s3EgressCIDRs` if your object store is
outside the cluster. The template rejects broad public routes there.

## Verify

Confirm the Ingresses exist. Three, not one:

```bash
kubectl get ingress -n agentarea
```

If any of the three hosts is missing from the output, its `host` value is empty
in `values.yaml`.

Confirm the backend advertises the right URL — this catches the derived-value
fallback silently pointing at a ClusterIP name:

```bash
kubectl get configmap -n agentarea agentarea-env-backend -o jsonpath='{.data.API_BASE_URL}'
kubectl get configmap -n agentarea agentarea-env-backend -o jsonpath='{.data.PUBLIC_S3_ENDPOINT}'
```

Check the endpoints answer from outside the cluster:

```bash
curl -sI https://api.example.com/health
curl -sI https://app.example.com
curl -s https://auth.example.com/health/ready
```

Then log in through the browser and confirm the session survives a page reload —
that is the check that catches a wrong `cookieDomain`, which no `curl` will
reveal.

Confirm the egress policy is both present and enforced:

```bash
kubectl get networkpolicy -n agentarea
kubectl run egress-check --rm -it -n agentarea \
  --image=curlimages/curl --restart=Never \
  --labels='app.kubernetes.io/managed-by=mcp-manager,app.kubernetes.io/component=mcp-server' \
  -- curl -s -m 5 http://169.254.169.254/
```

The request must time out. If it returns metadata, your CNI is not enforcing the
policy and the protection you think you have does not exist.

## Troubleshooting

**The site loads but login redirects to `localhost:4433`.** `kratos.urls.public`
is unset, so the chart used the internal service URL. Set `kratos.urls.public`
and `kratos.urls.publicBrowser`.

**Login succeeds, then every request is unauthenticated.**
`kratos.session.cookieDomain` is still `localhost`. Set it to your parent
domain.

**Login fails with a CORS error in the browser console.** Kratos rejects the
origin. `kratos.config.serve.public.cors.allowed_origins` ships pointing at a
staging domain; replace it.

**File uploads fail with a DNS error on an S3 hostname.**
`global.storage.publicEndpoint` is empty and the presigned URL points at the
in-cluster object store. Set it, and set `global.storage.cors.allowedOrigins`.

**Uploads reach the object store and are rejected with a CORS error.** The
endpoint is right but the bucket has no CORS rule. `allowedOrigins` was empty at
bootstrap, which skips applying one.

**MCP instances are created but never become reachable.** No Gateway matching
`mcpManager.gateway`, or Gateway API CRDs are not installed. The manager creates
HTTPRoutes that nothing programs.

**Provider icons are broken in the UI.** `API_BASE_URL` resolved to an internal
address. Icons are served by the backend at that URL; set
`global.api.publicUrl`.

**The egress NetworkPolicy exists and untrusted pods still reach the metadata
endpoint.** The CNI does not enforce NetworkPolicy. Nothing in the chart detects
this. Switch to a CNI that enforces it, or accept that MCP instance pods have
cluster-internal network access.

## Related

- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Configuration](/self-host/configuration)
- [Requirements](/self-host/requirements)
- [Troubleshoot a self-hosted deployment](/self-host/troubleshooting)
