# Sandbox host provisioning (Docker + gVisor)

Ansible that stands up a **dedicated host for running untrusted agent `bash()`**,
isolated with [gVisor](https://gvisor.dev) (`runsc`). It installs Docker,
registers gVisor, hardens the box, and deploys an authenticated OpenSandbox
server behind a source-allowlisted TLS proxy. The legacy single
`sandbox-executor` can remain online during a controlled migration.

## Why a dedicated host + gVisor

- **Isolation without special hardware.** gVisor's `systrap` platform interposes
  on syscalls entirely in userspace — it needs **no KVM / nested virtualization**,
  so it runs on any plain cloud VM (Timeweb, Aeza, DigitalOcean, Hetzner, YC).
  Untrusted code in the container talks to gVisor's sentry, not the host kernel.
- **Durable + fast state.** The host's local disk is real and long-lived, so the
  session workspace survives container restarts and IO is local — no object-FS or
  metadata DB needed.
- **Runtime is swappable.** `runsc` plugs in as a Docker runtime. On a bare-metal
  box with `/dev/kvm` you can later swap to a microVM runtime (`kata` / Firecracker)
  by changing one variable — the executor and control plane don't change.

## Where / what to run it on

Any Ubuntu 22.04/24.04 LTS VM you control. Start with one box (e.g. 4–8 vCPU,
8–16 GB, NVMe); it handles many sequential bash sessions. Add a second host for
blast-radius / maintenance drains before you need it for capacity. Keep
`mcp-manager` **off this box** — the Docker API on the sandbox host is the trust
boundary.

## Usage

```bash
cd deploy/sandbox-host
cp inventory.example.ini inventory.ini      # edit host IP / region
export SANDBOX_ACTIVATION_AUTH_SECRET=...    # the SAME value mcp-manager uses
export OPENSANDBOX_API_KEY=...               # from the regional GitOps Secret

# OpenSandbox-only dry run and apply; the legacy executor is not restarted.
ansible-playbook site.yml --check --diff --tags opensandbox
ansible-playbook site.yml --tags opensandbox
```

Then select the OpenSandbox adapter in both `mcp-manager` and
`mcp-sandbox-runner`:

```text
SANDBOX_PROVIDER=opensandbox
SANDBOX_OPENSANDBOX_URL=https://<opensandbox-host>
SANDBOX_OPENSANDBOX_API_KEY=<from Secret>
SANDBOX_OPENSANDBOX_ISOLATION=gvisor
SANDBOX_OPENSANDBOX_EGRESS_MODE=host-public
SANDBOX_OPENSANDBOX_USE_SERVER_PROXY=true
SANDBOX_OPENSANDBOX_SECURE_ACCESS=false
```

OpenSandbox's Docker runtime does not implement its `secureAccess` endpoint
tokens. Disabling that flag is accepted only with server-proxy routing. Direct
sandbox ports bind to `127.0.0.1`; the control API remains authenticated and
source-allowlisted.

## Kubernetes mode — one substrate for sandboxes *and* MCP servers

The mode above runs one executor container that the control plane calls over
HTTP. It isolates agent `bash()`, but MCP servers — including images a user
supplies — still run wherever the control plane can reach a Docker daemon,
usually beside the control plane itself, on its kernel.

Setting `sandbox_k3s_enabled: true` makes this host a single-node Kubernetes
cluster instead. Both untrusted workload types then run here as pods under
gVisor, through one mechanism:

```bash
ansible-playbook -i inventory.ini site.yml \
  -e sandbox_k3s_enabled=true \
  -e sandbox_activation_auth_secret="$SANDBOX_ACTIVATION_AUTH_SECRET"
```

This works because the control plane already speaks Kubernetes — it creates
Deployments, honours `runtimeClassName`, and already implements warm pools,
task→pod pinning and idle reaping against the Kubernetes backend. Nothing is
ported; the substrate simply starts answering the API it already talks.

k3s is used rather than a managed cluster for one reason: registering a custom
container runtime means editing containerd's configuration, which k3s supports
through a documented template. Managed providers generally revert it —
DigitalOcean states that changes to worker nodes "are overwritten by the
reconciler and do not persist."

The play writes a kubeconfig to `sandbox_k3s_kubeconfig_local_path`
(`./execution-cluster.kubeconfig` by default) with the API server address
rewritten from k3s's `127.0.0.1` to something the control plane can reach. Give
it to mcp-manager:

```
BACKEND_TYPE=kubernetes
KUBERNETES_KUBECONFIG=/etc/agentarea/execution.kubeconfig
KUBERNETES_RUNTIME_CLASS=gvisor
```

`KUBERNETES_KUBECONFIG` takes precedence over in-cluster credentials, so a
control plane running inside its own cluster still schedules onto this one. If
the file cannot be loaded, the manager refuses to start rather than quietly
using the cluster it happens to live in.

Through the Helm chart the same thing is a Secret plus two values, and the chart
derives the path:

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

The play refuses to finish unless a pod actually ran under gVisor: it schedules
one with `runtimeClassName: gvisor` and greps `dmesg` for the gVisor kernel
banner. A provisioning run that skipped that check would prove nothing.

In this mode the standalone executor container is not deployed — the sandbox is
a pod now, and leaving a second execution path on the box would only rot.

## Verify on the host

```bash
runsc --version
docker info | grep -i runtimes           # runsc listed
systemctl status opensandbox opensandbox-input-firewall sandbox-egress
docker inspect sandbox-<id> --format '{{.HostConfig.Runtime}}'  # must be runsc
# prove gVisor is actually the kernel the workload sees (NOT the host kernel):
docker run --rm --runtime=runsc alpine uname -a   # shows a gVisor kernel string
# metadata + private ranges are blocked from containers, public egress works:
docker run --rm --runtime=runsc alpine sh -c 'wget -qO- -T3 http://169.254.169.254/ || echo BLOCKED_OK'
```

Then run a real two-call task through mcp-manager (install in call 1, import in
call 2) and confirm state persists.

## Security posture (read this)

Shared-kernel isolation means **patch cadence is part of the posture**
(unattended-upgrades is enabled; schedule a reboot/livepatch window). What the
role enforces:

- gVisor `runsc` (systrap) as the container runtime — the real isolation wall.
- `--cap-drop ALL`, `--security-opt no-new-privileges`, pids/memory/cpu limits,
  `tmpfs /tmp`.
- `daemon.json`: `no-new-privileges`, `icc:false`, log rotation.
- **Egress firewall** (DOCKER-USER): blocks cloud metadata `169.254.169.254` and
  RFC1918 from containers (stops SSRF/credential theft + lateral movement) while
  leaving public egress for pip/npm. Add a private mirror as an ACCEPT rule if
  you use one (see `sandbox-egress.sh.j2`).
- HMAC-signed `/execute` (`SANDBOX_ACTIVATION_AUTH_SECRET`, **required** — the
  playbook refuses to run without it; no default). Still restrict the executor
  port to mcp-manager with a cloud firewall — the HMAC is the gate, the firewall
  is defense-in-depth.
- Never mount `docker.sock` into a sandbox; keep mcp-manager on a different host.

## Isolation model — what this increment does and does not give you

OpenSandbox runs **one disposable `runsc` container per task session**. A stable
Docker named volume is derived from the task ID and mounted at `/workspace`.
Terminating the sandbox releases CPU and memory but deliberately retains that
volume so unfinished agent work survives a later recreation. A separate
workspace-retention policy must remove volumes after the task itself is deleted
or passes its retention deadline.

The legacy executor still uses one long-lived shared container and exists only
for rollback during the migration. Do not treat it as the target isolation
model.

## Note on repo placement

This lives with the executor it configures (`agentarea/deploy/`) so it versions
with the code. The infra repo (`agentarea-hq/infra`) is Terraform for cloud
resources + Helm/ArgoCD — when you want the VM itself provisioned as code, add a
`timeweb`/`yc` Terraform module there that creates the box and hands its IP to
this playbook. Ask and it can be mirrored/moved.
