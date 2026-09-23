# agentarea-dataplane

AgentArea MCP data plane for an execution cluster: the mcp-manager data-plane API, and the namespace, admission and network policy the untrusted MCP servers it creates are confined to.

The AgentArea control plane runs MCP servers through a *data plane*: the
mcp-manager binary in data-plane mode, serving an authenticated HTTP API that
creates, proxies and deletes MCP server workloads. This chart installs one on an
**execution cluster** -- a cluster whose job is to run untrusted MCP servers,
separate from the one the control plane lives on -- together with everything
that confines those servers:

- a namespace for them, with Pod Security `baseline` and no ServiceAccount token;
- a ValidatingAdmissionPolicy that refuses any pod there without the sandboxing
  RuntimeClass (gVisor by default), whatever the data plane asks for;
- NetworkPolicy: only the data plane may reach them; they may reach cluster DNS
  and the public internet, not each other, the cluster or private networks;
- a Role for the data plane scoped to that namespace.

## Prerequisites

- Kubernetes 1.30+ (ValidatingAdmissionPolicy)
- A RuntimeClass that points at a sandboxing runtime, e.g. `gvisor` with handler
  `runsc`. Managed clusters rarely allow registering one; a k3s node does.
- A CNI that enforces NetworkPolicy (k3s's default does)
- Nodes that can pull the MCP server images the control plane will ask for

## Install

```bash
kubectl create namespace agentarea-system
kubectl -n agentarea-system create secret generic mcp-dataplane-token \
  --from-literal=token="$MCP_DATAPLANE_TOKEN"   # the value the control plane sends

helm install agentarea-dataplane agentarea/agentarea-dataplane \
  --namespace agentarea-system \
  --set dataPlane.id=my-execution-cluster \
  --set dataPlane.auth.existingSecret=mcp-dataplane-token
```

Then point the control plane at it, in the `agentarea` chart:

```yaml
mcpManager:
  dataPlane:
    url: http://<data plane address>:8090
    tokenSecret: <secret holding the same token>
```

Check it answers, and refuses without the token:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://<address>:8090/healthz                  # 200
curl -s -o /dev/null -w '%{http_code}\n' http://<address>:8090/dataplane/v1/instances   # 401
```

## Single-node host (k3s)

On a single node whose host firewall guards its ports, serve on the node address
instead of a Service, and allow the node to reach the MCP servers:

```yaml
exposure:
  hostNetwork:
    enabled: true
    bindAddress: 10.0.0.10        # the address the control plane routes to
workloads:
  networkPolicy:
    ingressFromCIDRs: [10.0.0.10/32, <pod bridge gateway>/32]
```

## Parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| image.repository | string | `"agentarea/agentarea-mcp-manager"` | mcp-manager image. The data plane is the same binary in data-plane mode. |
| image.tag | string | `""` | Defaults to the chart's appVersion. Keep equal to the control plane's tag. |
| image.pullPolicy | string | `"IfNotPresent"` | Pull policy for the data plane image. |
| imagePullSecrets | list | `[]` | Pull secrets for the data plane's own image. MCP server images are pulled by the nodes of this cluster; give them registry credentials there. |
| dataPlane.id | required | `""` | Stamped on every instance this data plane creates. A data plane refuses instances without its own id, so two data planes never claim each other's workloads. |
| dataPlane.auth.existingSecret | string | `""` | Secret holding the shared token: the value the control plane sends. |
| dataPlane.auth.existingSecretKey | string | `"token"` | Key in existingSecret. |
| dataPlane.auth.token | string | `""` | Creates the Secret from this value when existingSecret is empty. For development only: a value here lives in your values file and release history. |
| dataPlane.port | int | `8090` | Port the data-plane API listens on. |
| dataPlane.logLevel | string | `"INFO"` | Data plane log level. |
| exposure.hostNetwork.enabled | bool | `false` | Serve on the node's own address instead of a Service. For a single-node cluster whose host firewall already guards ports: a NodePort would be DNATed past INPUT, where that firewall lives. |
| exposure.hostNetwork.bindAddress | required with hostNetwork | `""` | Node address to bind, e.g. its VPC address. Binding 0.0.0.0 would publish the API on every interface the node has. |
| exposure.service.type | string | `"ClusterIP"` | Rendered when hostNetwork is off. |
| exposure.service.annotations | object | `{}` | Annotations for the Service, e.g. a cloud load balancer's internal-only switch. |
| exposure.service.loadBalancerSourceRanges | list | `[]` | For LoadBalancer: who may reach the API. Name the control plane. |
| workloads.namespace | string | `"agentarea-mcp"` | Namespace the MCP servers are created in. The data plane gets write access there and nowhere else. |
| workloads.createNamespace | bool | `true` | Create the namespace. Turn off to manage it yourself; keep its labels. |
| workloads.runtimeClassName | required | `"gvisor"` | RuntimeClass every MCP server runs with. It must exist on the cluster and point at a sandboxing runtime (runsc for gVisor). |
| workloads.isolationTier | string | `"untrusted"` | Default isolation tier for instances whose spec names none. |
| workloads.readOnlyRootFilesystem | bool | `false` | Read-only root for MCP servers. Off by default, as on the Docker data plane: real servers write under their image (Telethon keeps its session in /app). The sandboxing runtime keeps such writes inside the sandbox. |
| workloads.resources | object | `{"limits":{"cpu":"1","memory":"512Mi"},"requests":{"cpu":"100m","memory":"128Mi"}}` | Per-instance defaults. A spec may ask for less, never more than limits. |
| workloads.maxInstances | int | `8` | How many instances may exist at once. |
| workloads.podSecurity.enforce | string | `"baseline"` | Pod Security level enforced on the namespace. baseline rejects host namespaces, hostPath, privileged and added capabilities. |
| workloads.podSecurity.warn | string | `"restricted"` | Pod Security level that only warns. |
| workloads.admission.requireRuntimeClass | bool | `true` | Refuse any pod in the namespace that does not use runtimeClassName, through a ValidatingAdmissionPolicy, so no MCP server can reach the host kernel even through a data-plane bug. Needs Kubernetes 1.30+. |
| workloads.networkPolicy.enabled | bool | `true` | Close MCP servers to each other and to private networks. Needs a CNI that enforces NetworkPolicy (k3s does, through kube-router). |
| workloads.networkPolicy.ingressFromCIDRs | list | `[]` | Extra sources allowed to reach MCP servers. The data plane itself is allowed automatically when it runs as a pod; with hostNetwork its traffic comes from the node, so list the node address and the pod bridge gateway. |
| workloads.networkPolicy.denyCIDRs | list | `["169.254.0.0/16","10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","100.64.0.0/10"]` | Destinations MCP servers may not open connections to. Covers the cloud metadata service, private ranges (including this cluster's pod and service ranges and the network the control plane sits on) and carrier-grade NAT. |
| workloads.networkPolicy.dns | object | `{"namespace":"kube-system","podLabels":{"k8s-app":"kube-dns"}}` | Labels of the cluster DNS pods MCP servers may query. |
| workloads.networkPolicy.extraEgress | list | `[]` | Additional egress rules, as NetworkPolicy egress entries. For a host that REDIRECTs some traffic to a local proxy, allow the redirect target here. |
| sandboxPolicy | object | `{"providerProvisioningTimeout":"5m","providerSessionTTL":"24h","taskIdleTTL":"15m","taskLeaseTTL":"10m"}` | Required by the Kubernetes backend at start although a data plane runs no agent sandboxes: the task lease is read unconditionally. |
| extraEnv | list | `[]` | Extra environment for the data plane container. |
| resources | object | `{"limits":{"cpu":"1","memory":"512Mi"},"requests":{"cpu":"50m","memory":"64Mi"}}` | Resources of the data plane itself. |
| nodeSelector | object | `{}` | Scheduling for the data plane pod. MCP servers are placed by their RuntimeClass. |
| tolerations | list | `[]` | Tolerations for the data plane pod. |
| affinity | object | `{}` | Affinity for the data plane pod. |
