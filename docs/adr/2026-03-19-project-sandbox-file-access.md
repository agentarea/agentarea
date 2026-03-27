# ADR-001: Project Sandbox File Access Strategy

**Date:** 2026-03-19
**Status:** Accepted
**Deciders:** Engineering team
**Related spec:** `docs/superpowers/specs/2026-03-16-projects-design.md`

---

## Context

Projects store files in MinIO at `projects/{project_id}/files/`. Agents need to access these files during task execution via filesystem tools (`read_file`, `write_file`, `list_dir`, `glob`, `grep`) and run arbitrary scripts (`run_script`) that operate on those files.

The warm pool provides pre-warmed Kubernetes pods for ephemeral script execution. The challenge: how do project files in MinIO get into the execution environment?

---

## Decision

**Two-tier architecture:**

1. **File tools** (`read_file`, `write_file`, `list_dir`, `glob`, `grep`, `get_project_info`) → direct MinIO S3 API calls from Temporal activities. No pod needed.
2. **`run_script`** → stateless warm pool + Go activation service sync: copy project files to pod's `/workspace/` (emptyDir) before execution, copy changed files back after. Pod returns to pool immediately after.

---

## Options Evaluated

### For file tools

These don't require a pod. MinIO's S3 API supports `GetObject`, `PutObject`, `ListObjectsV2`, and `GetObject` (for grep via stream scanning) natively. Routing file tools through a pod just to do what S3 already does natively would add unnecessary latency, pod acquisition cost, and complexity.

**Decision: Python Temporal activities using boto3 directly** (same pattern as `ContextStore`).

---

### For `run_script` (pod-level execution required)

| Option | Approach | Rejected because |
|---|---|---|
| **s3fs FUSE mount** | Mount MinIO bucket as filesystem inside pod | Requires `SYS_ADMIN` capability + `/dev/fuse` device in pod spec. Latency is high for write-heavy workloads. Unreliable under concurrent writes. Security surface area increase. |
| **CSI driver (S3-backed PV)** | One PVC backed by the S3 bucket | One PVC per project → 500 projects = 500 PVCs (unmanageable lifecycle, quota pressure). One PVC for the whole bucket → path traversal: agent can run `cd ../../` and access other projects' files. No isolation between projects. |
| **mc mirror (MinIO CLI)** | Run `mc mirror` inside pod to sync before/after | Requires MinIO CLI in pod image (~100MB addition). Tight coupling to MinIO-specific tooling rather than standard S3. Image rebuild needed. |
| **Pre-signed URLs + curl** | Generate pre-signed URLs, download files with curl at pod init | Complex to implement for directories (requires listing + N downloads). Hard to track which files changed for sync-back. Not idiomatic. Error-prone for large file trees. |
| **Sync-to-local via Go activation service** ✓ | Add setup/teardown endpoints to existing activation service on each warm pool pod | **Chosen** — see below. |

---

### Chosen: Sync-to-local via Go activation service

Each warm pool pod runs an activation service (port 8080) for lifecycle management. We add two endpoints:

```
POST /workspace/setup
Body: { "minio_prefix": "projects/{id}/files/", "work_dir": "/workspace/" }
→ Downloads all files from MinIO prefix to /workspace/ using Go AWS SDK

POST /workspace/teardown
Body: { "minio_prefix": "projects/{id}/files/", "work_dir": "/workspace/" }
→ Uploads all files from /workspace/ back to MinIO, then wipes /workspace/
```

`/workspace/` is an `emptyDir` volume on the pod — it contains **only** the target project's files.

**Why this wins:**

- **Security via isolation**: `cd ../../` is harmless — `emptyDir` contains nothing but the current project's files. No other project's data is present. No capability escalation needed.
- **Stateless design preserved**: existing `FindAvailablePod` + `ExecuteInPod` + `ReturnToPool` pattern is unchanged. No session manager, no pod labelling, no long-lived assignments.
- **Minimal implementation surface**: ~100 lines of Go in the existing activation service. Go AWS SDK is already a dependency.
- **No image changes**: no new binaries, no MinIO CLI, no FUSE drivers.
- **Package persistence is free**: packages installed to `/workspace/venv/` (Python) or `/workspace/node_modules/` (Node) live inside `/workspace/` and are synced back to MinIO automatically. They're available on the next run.

---

## Consequences

### Positive
- File tools (`read_file`, `write_file`, etc.) have no pod overhead — direct S3 calls are faster and cheaper.
- `run_script` sandbox is isolated by construction (emptyDir), not by policy.
- Warm pool remains fully stateless — no session lifecycle to manage.
- Packages installed into `/workspace/` persist across runs via MinIO sync.

### Trade-offs
- `run_script` requires two extra HTTP calls per execution (setup + teardown).
- System-level package installs (`apt install`, `brew install`) are lost between runs on standard agents. Mitigation: agents should install to `/workspace/venv/` (Python), `/workspace/node_modules/` (Node), or maintain a `/workspace/.agentarea/setup.sh` that the activation service runs automatically after setup.
- Last-write-wins on concurrent tasks modifying the same file (same policy as S3 directly — acceptable for v1).

---

## Future Extension: Claw Agent Type

Standard agents use the stateless approach above. A future **Claw** agent type will extend this with a persistent sandbox:

- Dedicated pod with a PVC for the OS/packages layer (`/usr/local/lib`, `~/.local`)
- Project files remain source-of-truth in MinIO (same sync in/out as above)
- The OS layer accumulates installed tools across runs — no re-setup needed
- Claws are named as a product concept (analogous to OpenClaw's always-on agent instances)

**Limits to prevent resource abuse:**

| Tier | Claw quota | Idle policy |
|---|---|---|
| OSS | 0 (stateless agents only) | N/A |
| Pro | 2 per workspace | Hibernate after 24h idle |
| Enterprise | Configurable | Configurable |

Hibernate = release pod back to pool, snapshot PVC state, restore on next task activation (~30s cold start). This defers PVC costs to active projects only.

The Claw extension does not change the file sync architecture — MinIO remains source-of-truth in both modes. The only difference is whether the OS/packages layer is ephemeral (standard) or persistent (Claw).

**Claw is deferred to post-MVP.** The stateless architecture ships first and works for all use cases where agents can install to `/workspace/`.
