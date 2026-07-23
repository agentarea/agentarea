# Sandbox host provisioning (Docker + gVisor)

Ansible that stands up a **dedicated host for running untrusted agent `bash()`**,
isolated with [gVisor](https://gvisor.dev) (`runsc`). It installs Docker,
installs and registers gVisor, hardens the box, and runs the AgentArea
sandbox-executor under a userspace kernel.

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

# dry run
ansible-playbook site.yml --check -e sandbox_activation_auth_secret="$SANDBOX_ACTIVATION_AUTH_SECRET"
# apply
ansible-playbook site.yml -e sandbox_activation_auth_secret="$SANDBOX_ACTIVATION_AUTH_SECRET"
```

Then point the control plane at it: set `SANDBOX_EXECUTOR_URL=http://<host>:8080`
on mcp-manager (the docker backend calls `/execute` there over the signed
transport). The host is region-labelled via `sandbox_region`; once control-plane
placement targets are declared, that label is how a task routes here.

## Verify on the host

```bash
runsc --version
docker info | grep -i runtimes           # runsc listed
systemctl status agentarea-sandbox-executor sandbox-egress
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

This runs **one long-lived executor container** under gVisor, serving all tasks
(state separated per task by workspace dir + non-root uid, exactly like the dev
docker backend — but now the whole container is gVisor-isolated from the host).

- **Gained:** untrusted code no longer touches the host kernel; host-level
  multi-tenant escape needs a gVisor escape, not just a container escape.
- **Not yet:** per-tenant isolation *between* tasks (they share one gVisor
  sandbox). Full per-task isolation = the **HostPool provider** (per-task
  disposable `runsc` container + per-task volume, assignment in the store) — the
  next stage. This host is already provisioned correctly for it; only what runs
  on top changes.

## Note on repo placement

This lives with the executor it configures (`agentarea/deploy/`) so it versions
with the code. The infra repo (`agentarea-hq/infra`) is Terraform for cloud
resources + Helm/ArgoCD — when you want the VM itself provisioned as code, add a
`timeweb`/`yc` Terraform module there that creates the box and hands its IP to
this playbook. Ask and it can be mirrored/moved.
