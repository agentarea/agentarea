---
title: Artifacts
type: concept
summary: How files an agent produces become durable — content-addressed objects, an immutable manifest per generation, and a compare-and-swap pointer — and how you get them back.
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/execution/events
  - /concepts/execution/durable-execution
  - /concepts/sandbox/the-file-model
last_updated: 2026-07-29
---

# Artifacts

An artifact is a file the task produced that outlives the sandbox that produced
it. Artifacts live in S3-compatible object storage, addressed by the SHA-256 of
their contents, and are named through a manifest that maps ordinary relative
paths onto those objects.

## The problem

An agent writes `report.pdf` in a container that will be destroyed. Three things
have to be true afterwards, and none of them is free.

The bytes must still exist and must be the bytes the agent wrote — not a
truncated copy, not a later overwrite by a second execution. The file must still
be reachable by the name a human recognizes, because nobody asks for
`a3f5b9...`. And the download must go through the platform's authorization, so
that "list this task's files" cannot become "list this bucket".

Getting any one of these wrong produces a specific failure: a deliverable the
user cannot reach, a deliverable that is silently the wrong version, or a
storage URL that leaks past workspace scoping.

## How AgentArea approaches it

Two stores exist, and they are not the same thing.

**`ArtifactService`** is a workspace-scoped object store keyed by path:
`workspaces/{workspace_id}/{path}`. Callers pass the plain path and the service
prepends the workspace prefix, so a cross-tenant read requires passing a
different `workspace_id`. Writes record a `sha256` in user metadata and set the
S3-native `ChecksumSHA256`. This backs project files and general workspace
storage.

**`S3WorkspaceRepository`** is the task workspace, and this is the
content-addressed one. Everything below describes it.

### Content-addressed bodies

A file body is written to `workspaces/{ws}/tasks/{task}/objects/{sha256}` with
`IfNoneMatch: *`. The key is the digest of the content, so the object is
immutable by construction. If the key already exists, the write is not a
conflict — it is the same bytes, and the existing object's size and digest are
checked to confirm that. A genuine mismatch raises `WorkspaceConflictError`
rather than overwriting.

### Naming through a manifest

A manifest is a JSON document listing entries:

```json
{
  "relative_path": "reports/summary.md",
  "object_uri": "s3://artifacts/workspaces/ws1/tasks/t1/objects/9f86d0...",
  "object_version_or_etag": "\"a1b2c3\"",
  "sha256": "9f86d0...",
  "size": 1284,
  "content_type": "text/markdown",
  "mode": 420,
  "deleted": false
}
```

The manifest is itself immutable, stored at
`manifests/{generation}-{sha256}.json`. Paths are canonical POSIX relative
paths; anything absolute, containing `..`, or non-canonical is rejected before
it reaches storage.

### Generations and compare-and-swap

Every commit produces a new generation. The manifest records its own
`generation`, the `base_generation` it was derived from, and a `fencing_token`
from the writer's lease. A small `current.json` pointer names the live
generation and is advanced with `IfMatch` on its ETag.

That gives three independent rejections instead of a last-write-wins clobber:

- a stale `base_generation` fails the caller's explicit expectation check,
- a stale lease fails the fencing-token assertion at commit time,
- a concurrent pointer advance fails the compare-and-swap.

Two sandbox executions racing on the same task therefore produce one committed
generation and one rejected commit, not a silently merged workspace.

Readers verify what they load. `_entries_for_ref` re-hashes the manifest body
against the reference's `manifest_sha256` and re-checks its identity tuple
before trusting a single entry.

### How artifacts get produced

Three paths write into the task workspace, and all three go through the same
repository:

- **Copy-out from the sandbox.** When the shell tool returns, it copies each
  reported artifact out of the ephemeral sandbox into the durable workspace
  synchronously, before the tool result reaches the model — copy before claim, so
  the agent cannot assert success over a file that was never persisted. The
  bytes are re-hashed on read and a mismatch against the digest the executor
  reported is refused, so a swap in the live workspace between report and read
  cannot commit content the executor never saw.
- **Task attachments.** A client uploads to a staging key with a presigned PUT
  whose signature binds `ChecksumSHA256`, so the object store rejects a body
  that does not hash to the declared digest. The API then calls `attach_object`,
  which verifies the staged object's identity and issues a server-side
  `CopyObject` into the task's `objects/{sha256}` slot. The bytes never transit
  the API process.
- **Skill materialization and project inputs.** `put_files` commits a batch as
  one generation; `import_workspace_prefix` streams a trusted project prefix in
  one object at a time through a bounded spool, so neither the worker nor a
  sandbox request ever holds the whole project.

### How artifacts get retrieved

```
GET /v1/agents/{agent_id}/tasks/{task_id}/artifacts
GET /v1/agents/{agent_id}/tasks/{task_id}/artifacts/files/{artifact_path}
```

The list endpoint returns entries under the public path
`tasks/{task_id}/workspace/{relative_path}`, each with an AgentArea download URL
— not an object-store URL. The download endpoint verifies the task belongs to
the agent and the caller's workspace, then streams the object through the API.

`ArtifactService.stream` verifies before it yields: it reads the whole body into
a bounded spool, hashes it, and compares against the stored digest. If the
digest is missing or the content does not match, it raises
`ArtifactIntegrityError` and no bytes are returned.

### The completion gate

The artifact validator that gates task completion is deliberately narrow. It
returns identity-only evidence — path, validator, `sha256`, `size` — and issues
with stable codes. It answers "does this file exist and is this its digest",
not "is this a valid PDF". Deciding whether the content is *right* belongs to
the task's own success criteria, not to the storage layer.

## Why not address artifacts only by digest

A pure content-addressed store has no names and no ordering. `9f86d0...` is not
something an agent can reference in its next tool call or a user can find in a
list. The manifest is the naming layer, and separating it from the bodies is
what makes both properties available at once: bodies are immutable and
deduplicated within the task, while names are mutable and versioned.

## Why not mutable paths with last-write-wins

The simple design writes `tasks/{task}/workspace/report.md` directly and lets
the newest write win. It fails the moment two executions touch the same task —
which is the normal case for a retried activity or a re-provisioned sandbox.
The corruption is silent: no error, only a file whose contents came from
whichever call finished second. The lease plus fencing token plus CAS pointer
converts that into a rejected commit, which is loud.

## Why not hand out presigned download URLs

A presigned URL is a bearer token for an object-store key. It leaks the bucket
layout, bypasses AgentArea's workspace check and audit trail, and cannot be
revoked before expiry. Streaming through the API costs bandwidth through the
platform and buys authorization, audit, and a stable URL that survives a storage
migration. Presigned URLs are still used for *upload*, where the checksum
binding makes the object store itself the verifier.

## Limits

- **Deduplication is per task.** `objects/{sha256}` sits under the task prefix,
  so identical bytes in two tasks are stored twice.
- **A rejected commit can leave an orphan.** The total-bytes quota is checked at
  commit, after the body has already been uploaded or copied. An attach or a
  `put_files` that pushes the workspace over quota leaves an unreferenced blob
  behind.
- **Nothing garbage-collects old generations.** Superseded manifests and the
  objects only they referenced stay in the bucket.
- **Caps are hard, and there are four.** 10,000 files and 2 GiB total per task
  workspace, 256 MiB per file at the repository; the shell tool's copy-out
  applies its own tighter caps of 16 MiB per artifact and 1 GiB of durable bytes
  per task, and refuses the copy rather than truncating.
- **Only the task workspace is downloadable through the task API.** The artifact
  endpoints serve `tasks/{task_id}/workspace/...` and 404 on anything else.
- **Verification is complete-before-first-byte.** `stream` buffers and hashes the
  entire object before yielding, spooling to disk past 8 MiB. Time to first byte
  scales with object size.
- **Provenance is best-effort.** A failed artifact-event write is logged and the
  file operation still succeeds, so the audit trail can be incomplete where
  storage succeeded.
- **The lease is time-based.** It defaults to 3600 seconds. A writer that stalls
  past its lease loses the fencing-token assertion at commit and must retry.

## Related

- [Tasks](/concepts/execution/tasks) — the completion gate that validates these.
- [Events](/concepts/execution/events) — `artifact.created` and
  `artifact.updated` parts.
