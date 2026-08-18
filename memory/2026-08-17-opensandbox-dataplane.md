# OpenSandbox data-plane investigation — 2026-08-17

## Status

DONE. The server is reachable without SSH through a short-lived Kubernetes
proxy pod in the same Timeweb VPC.

## Symptom

The outbound data-plane agent supported Docker MCP and Kubernetes sandbox independently, but rejected the required mixed `Docker MCP + external OpenSandbox` configuration before startup.

## Root cause

`internal/connectorcomposition` deliberately returned `ErrAgentLocalSessionStoreNotImplemented` for every external sandbox provider, and both composition and config validation prohibited a sandbox provider when MCP used Docker. The connector transport and control-plane sandbox adapters already supported the required command flow.

## Fix

- Compose MCP and sandbox providers independently.
- Allow Docker MCP and an external sandbox provider on one logical data plane.
- Require an explicit agent-local Redis/Valkey URL for durable external-provider bindings.
- Close provider state and backend resources during agent shutdown.
- Extend the raw-VM E2E harness with sandbox-enabled control-plane configuration and an isolated OpenSandbox provider fixture.

## Evidence

- Targeted unit, race, vet, Compose validation, and diff checks pass.
- On the disposable `dbw` test, the agent reported `{"mcp": true, "sandbox": true}` while OpenSandbox health was green. This fixture was then completely removed at the user's request; `dbw` is back to `{"mcp": true, "sandbox": false}` and MCP HTTP returns 200.
- Claude history proves the intended VM was formerly reached as `root@72.56.235.217`; production configuration now reaches the same workload host privately at `10.42.0.10:8081` (OpenSandbox) and `10.42.0.10:8090` (MCP data plane).
- The dedicated Timeweb kubeconfig reaches the `10.42.0.0/24` VPC. A temporary socat pod proved TCP reachability to `10.42.0.10:22` and was deleted afterward.

## Final verification

- A proxy pod forwarded OpenSandbox `10.42.0.10:8081` and the authenticated
  legacy MCP data plane `10.42.0.10:8090`; it was deleted after the run.
- One outbound connector advertised `{"mcp": true, "sandbox": true}`.
- OpenSandbox provisioned a real gVisor sandbox, wrote `proof.txt`, read back
  `proxy-pod-opensandbox-ok`, and listed the file.
- MCP `initialize` traversed connector -> authenticated legacy proxy -> VM
  container and returned HTTP 200 from weather server `3.4.6`.
- Test sandbox and MCP instances were retired. `dbw` was restored to MCP-only
  and reverified with `{"mcp": true, "sandbox": false}` plus MCP HTTP 200.

## Related fixes

- Process `/health` no longer performs remote workload inventory scans; the old
  behavior flooded `kubectl port-forward` with hanging legacy list requests.
- Legacy ownership labels are translated only after the authenticated legacy
  data plane has enforced its own host ownership.
- Provider proxy base paths are preserved when appending `/mcp`.
