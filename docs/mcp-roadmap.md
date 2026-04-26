# MCP Roadmap

Future work for the MCP runtime. Phase 1 is shipped (this branch). Everything below is queued.

## Scope discipline

mcp-manager + Python MCP libs do **only MCP-aware things**. Anything generic to K8s lives in the Helm chart or in admin-installed cluster operators (Kyverno, sigstore policy-controller, KEDA, Cilium, Trivy operator). The more we hardcode in Go, the more friction integration teams face.

| Concern | In our code? | Owner |
|---|---|---|
| MCP lifecycle (provision, verify, dispatch) | yes | mcp-manager + Python `verify()` |
| Catalog model + spec resolution | yes | Python catalog libs |
| KEDA `HTTPScaledObject` per instance | yes (per-instance names) | mcp-manager |
| OAuth handshake for MCPs | yes | Python (existing scaffolding) |
| Bundle composition + dispatch | yes | Python |
| NetworkPolicy / ResourceQuota / LimitRange | no | Helm + admin |
| ImagePullPolicy / pull secrets | no | Helm + admin |
| Image vulnerability scanning | no | Admin: Kyverno + Trivy operator |
| Cosign signature verification | no | Admin: sigstore policy-controller |
| Audit log / SIEM export | no | Admin: OpenTelemetry → SIEM |
| PSS, gVisor / Kata RuntimeClass | no | Admin: namespace label / RuntimeClass |
| Wallet / metering / billing / budgets / vendor splits | no | Separate stream (existing budget-guard code may be reusable) |
| Payment-provider plugins (Stripe / x402 / MPP) | no | Separate stream |

## Catalog reality

Catalog substrate already exists. Don't rebuild.

- DB: `MCPServer` (catalog spec, `is_public`, `json_spec`, `registry_url`) + `MCPServerInstance` (instantiated)
- Registry sync: `Registry` + `RegistryItem` tables, periodic sync from JSON/YAML/GitHub sources, auto-creates `MCPServer` rows
- API: `/v1/mcp-servers` (catalog), `/v1/mcp-server-instances` (instances), `/v1/registries/catalog/search`
- Frontend: gallery + spec card + create-from-spec flow exist; manual "add from form" also works

Gaps: registry-management UI, seamless add-from-catalog flow, marketplace UX (featured / trending / verified-publisher).

## Phase 1 (shipped — see git history on `feat/mcp-lifecycle-phase1`)

- `verify()` is the single provisioning path; Redis eventsub Create handlers disabled
- `CreateInstance` returns ack-only; Python's retry loop handles readiness
- TCP probes (portable across all MCP images, no `/health` assumption)
- `--transport=stdio` stripped for K8s docker-type
- Idempotency in `CreateInstance` (TOCTOU-safe with `IsNotFound` check + Deployment existence verification)
- `ImagePullPolicy` configurable via `K8S_IMAGE_PULL_POLICY`
- mcp-bridge: `HOME=/tmp`, npm/uv cache dirs, concurrent-session id-collision fix
- Python verify: 120s deadline with extended retry slots
- 26 tests added (16 Python + 10 Go)

End-to-end k3s smoke verified for all 4 types: `url`, `command` (npx + uvx), `docker` (HTTP-native), `bundle`.

## Phase 2 — KEDA HTTP add-on (scale-to-zero) — 1 wk

Idle MCPs should cost nothing; first request wakes the pod.

- Helm chart dep + `mcpManager.scaleToZero.enabled=false` flag (off by default)
- Per-instance `HTTPScaledObject` CRD created alongside Deployment in `internal/backends/kubernetes_resources.go`
- k3d smoke verifying suspend/wake works
- **Verification:** idle pod scales to 0; first request wakes it; dispatch returns within cold-start budget

## Phase 2.5 — DEFERRED: restore Temporal orchestration

Phase 1 deleted `start_instance_workflow.py` / `stop_instance_workflow.py` to ship fast. Known regressions:

- Cleanup-on-error is best-effort (orphan resources on context cancel — observed in smoke)
- No replay if mcp-manager crashes mid-create
- Per-step observability collapsed into `container_failed` / `list_tools_timeout`
- Each future lifecycle concern (scan, sign-verify, OAuth, secret resolution) would pile onto the Go monolith

Decision: don't do as a standalone phase — no user-facing win, 1.5 wks of invisible refactor.

**Bundle it** with the first phase that adds a multi-step lifecycle concern. Triggers to pull forward:

- First multi-step lifecycle phase needing it, OR
- First production incident where opaque failure mode costs > 1 day debugging, OR
- First customer asking for per-step observability

Mitigation while deferred: orphan-resource cleanup runbook in `docs/operations.md`.

## Phase 3 — Catalog UX gaps — 2 wks

Catalog substrate exists; close the UX loop.

- Add-from-catalog flow on frontend (pick spec → instantiate, no manual form)
- Registry-management UI (admin browse / configure registries)
- **Verification:** pick spec from catalog → instance verification.succeeded with no manual form fill; admin can add/edit/remove a registry from the UI

## Phase 4 — Image-policy + NetworkPolicy primitive — 1 wk

Interface + permissive default. Self-hosters keep all knobs off; cloud turns them on via config. Scanner / cosign verification stay admin-installed (Kyverno, sigstore policy-controller).

- `MCPImagePolicy` Go interface (`Validate` + `ResolvePullPolicy`)
- Two impls: `permissive` (default — accepts anything) and `allowlist` (config-driven)
- Helm values: `imagePolicy.{allowedRegistries, requireDigest, blockMutableTags}` — empty / off by default
- Per-MCP `NetworkPolicy` (default-deny egress, allowlist declared URL host) — opt-in via Helm value, off by default
- Per-image `ImagePullPolicy` derivation (digest → `IfNotPresent`, tag → `Always`)
- **Verification:** `imagePolicy.allowlist` set → bad image rejected with structured error before reaching k8s; NetworkPolicy with declared URL allowlist blocks egress to off-list hosts

## MCP system-complete gate (after Phase 4, ~4 wks)

Same binary in every distribution; operational policy via Helm + admin operators. Self-hosters run anything; our cloud tightens via config. **MCP work stops here.**

## Parked workstreams (NOT part of MCP shipping)

### Pricing / billing / wallet / budgets / vendor splits

Split into a separate stream. We already have an existing budget-guard approach in the codebase that may be reusable. When this stream resumes, revisit budget-guard first, decide reuse-vs-rewrite, then plan its own phased rollout.

Defers: wallet ledger, per-call billing wiring, per-agent budgets, vendor revenue split, billing-purpose metering pipeline, payment-provider plugins.

### Image scanner / cosign verify

Admin's job. If a user wants vulnerability gating: install Kyverno + Trivy operator. If signature verification: install sigstore/policy-controller. We don't ship our own plugin interface until a customer asks.

## Optional polish (customer-driven)

Each shipped when first user actually asks. None blocks the system-complete gate.

- gVisor / Kata RuntimeClass (untrusted-image isolation)
- ResourceQuota per workspace
- Audit log + SIEM export
- BYOC / air-gap mode
- OAuth-enabled MCPs (existing scaffolding to finish)
- Persistent volumes
- WebSocket / streaming MCP transport
- Bundle composition v2
- MCP versioning + auto-update notifications
- Cross-workspace MCP sharing
- Catalog pre-warm pool
- Session affinity

## Anti-patterns

- Don't rebuild the catalog — it exists; close UX gaps only
- Don't bake payment providers into mcp-manager
- Don't pre-build for hypothetical enterprise (SOC2, BYOC, audit) — wait for first ask
- Don't optimize cold-start before users complain (KEDA defaults are fine)
- Don't write our own scale-to-zero — use KEDA HTTP add-on
- Don't write our own image scanner — let admins wire Trivy / Kyverno
- Don't hardcode K8s policy in Go when a Helm template does the job
- Don't restore Temporal as a standalone refactor — bundle it with a phase that needs it

## First 4 weeks after Phase 1 merge

- Week 1: Phase 2 KEDA HTTP add-on
- Week 2-3: Phase 3 catalog UX gaps
- Week 4: Phase 4 image-policy + NetworkPolicy primitive
