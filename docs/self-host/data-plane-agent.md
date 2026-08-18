---
title: Connect a VM as a data plane
type: guide
summary: Attach an ordinary Linux VM through an outbound-only AgentArea agent.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/kubernetes
  - /self-host/networking
last_updated: 2026-08-17
---

# Connect a VM as a data plane

AgentArea can attach an ordinary Linux VM without opening an inbound port on
that VM. The data-plane agent makes outbound HTTPS connections to the control
plane and stores only its own node identity.

The agent does not install Docker, OpenSandbox, E2B, Kubernetes, k3s, or
firewall rules. A newly attached VM has no workload capabilities. You may
explicitly bind a provider that is already installed on the host.

## Create the data plane

From a machine where the AgentArea CLI is authenticated:

```bash
agentarea data-planes create \
  --display-name="edge-eu-1" \
  --region="eu-west-1"

agentarea data-planes enrollment-token <data-plane-id>
```

The enrollment token expires after ten minutes and can be used only once.
Copy it directly to the target VM; do not put it in source control or an
environment file.

## Attach the VM

Run the pinned installer on the target VM. It verifies the release checksum,
creates a dedicated non-login user, enrolls the node, consumes the token, and
starts a hardened systemd service:

```bash
sudo scripts/install-data-plane-agent.sh \
  --version vX.Y.Z \
  --control-plane-url https://agentarea.example.com \
  --connector-gateway-url https://agentarea.example.com \
  --data-plane-id <data-plane-id> \
  --enrollment-token-stdin
```

Paste the one-time token when prompted. With no provider option, the VM
connects successfully and advertises neither MCP nor sandbox capability.

### Use existing Docker for MCP

If Docker is already installed on the VM and you want this node to run MCP
containers, add one explicit option to the same command:

```bash
--mcp-provider docker
```

The installer verifies the existing Docker executable and socket group. It
does not install or reconfigure Docker. Docker socket access is effectively
root-equivalent access to this VM, so enable it only on a dedicated data-plane
host.

Sandbox is independent of MCP. Selecting Docker does not install or enable a
sandbox provider. OpenSandbox, E2B, Kubernetes, and future runtimes attach
through their own provider adapters.

## Verify the connection

```bash
sudo -u agentarea-data-plane-agent \
  agentarea-data-plane-agent doctor \
  --config /etc/agentarea-data-plane-agent/config.json

systemctl status agentarea-data-plane-agent
```

The logical data plane should report a recent heartbeat and only the
capabilities backed by providers that initialized successfully. If a provider
is unavailable, the agent fails closed and does not advertise it.

## Network and identity boundary

The VM needs outbound HTTPS and DNS only. Do not publish a listener or create
an inbound firewall rule for the agent. Its identity is stored with mode
`0600` under `/var/lib/agentarea-data-plane-agent/`; retiring the logical data
plane revokes its node credential.

For Kubernetes, deploy the same outbound agent with the dedicated Helm chart.
The chart also installs no workload runtime or inbound Service.
