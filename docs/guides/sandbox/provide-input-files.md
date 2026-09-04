---
title: Provide input files to a task
type: guide
summary: Upload files and attach them to a task so the agent finds them on the sandbox filesystem at known relative paths.
prerequisites:
  - /concepts/sandbox/the-file-model
related:
  - /guides/sandbox/run-a-command
  - /guides/sandbox/collect-artifacts-and-logs
  - /reference/limits
  - /concepts/execution/artifacts
last_updated: 2026-07-29
---

# Provide input files to a task

Do this when the agent's work starts from data you already have — a CSV to
analyse, a document to summarize, an archive to inspect. The files are staged,
copied into the task's own workspace, and materialized onto the sandbox
filesystem before the first command runs.

Do not use this to give an agent standing reference material that every task
needs. That belongs in the organization context store, which agents read without
it being attached per task.

## Prerequisites

- A configured object store behind the artifact service
- An agent equipped with a tool that reads files — the shell
  (`agentarea/shell`) or the file tool (`agentarea/files`)
- [The file model](/concepts/sandbox/the-file-model) for how task scoping works

## Steps

### 1. Stage the file and get a ref

Two ways, and they produce the same kind of `staging/{id}/{filename}` ref.

**Server-proxied, for small files and quick scripting.** One request, no checksum
to compute, but the bytes pass through the API process:

```bash
curl -X POST "$AGENTAREA_URL/v1/files" \
  -H "Authorization: Bearer $TOKEN" \
  -F "purpose=attachment" \
  -F "file=@report.csv"
```

The response carries `ref`, `filename`, `size`, `sha256`, and `content_type`.

**Presigned direct upload, for large files or when you want content
verification.** Pick this when the file is big enough that proxying it is
wasteful, or when you want the store itself to reject a corrupted body:

```bash
SHA=$(shasum -a 256 report.csv | cut -d' ' -f1)
SIZE=$(wc -c < report.csv)

curl -s -X POST "$AGENTAREA_URL/v1/files/upload-url" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"filename\":\"report.csv\",\"sha256\":\"$SHA\",\"size\":$SIZE,\"content_type\":\"text/csv\"}"
```

The response gives `ref`, `upload_url`, and `expires_in` (3600 seconds). The
declared SHA-256 is bound into the signature as `ChecksumSHA256`, so the object
store rejects a body that does not hash to it. Upload with:

```bash
curl -X PUT "$UPLOAD_URL" \
  -H "x-amz-checksum-sha256: $(printf %s "$SHA" | xxd -r -p | base64)" \
  --upload-file report.csv
```

### 2. Create the task with the refs

Pass the refs in `attachments`:

```bash
curl -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Summarize the attached CSV: row count and column names.",
    "attachments": ["staging/6f1c.../report.csv"]
  }'
```

The API HEADs each ref to resolve its verified digest, size, and content type,
then copies it server-side into the task's content-addressed store. The bytes
never transit the API process on this leg.

### 3. Let the agent find them

Each attachment lands at `inputs/attachments/<filename>`, and the agent is told
so in its prompt — the exact relative paths are listed, with instructions not to
ask for the files again. Before the first bash command runs, the shell tool
copies the task's durable inputs onto the sandbox filesystem at the same relative
paths, so `cat inputs/attachments/report.csv` works.

Files staged under a project prefix are materialized the same way at
`inputs/project/`.

## Verify

List what the task actually received:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $TOKEN"
```

Attachments appear under `inputs/attachments/`. To confirm they reached the
sandbox disk rather than only durable storage, have the agent run
`ls -la inputs/attachments/` and check the event stream for the output — the file
should be listed with its expected byte size.

## Troubleshooting

**422 "Invalid attachment ref".** The ref does not begin with `staging/`. Only
staged refs are accepted; a workspace path or an arbitrary object key is
rejected. Re-stage with `purpose=attachment` or the presigned endpoint.

**404 "attachment ref not found".** The staging object is not there — usually the
presigned PUT was never completed, or it failed the checksum and the store
discarded it. Confirm the upload returned 200 before creating the task.

**422 "attachment integrity digest is unavailable".** The staged object has no
recorded SHA-256, so the server cannot verify what it is copying. This happens
when an object was placed in the staging prefix by something other than the two
supported paths.

**413 on upload or on task create.** A single attachment is capped at 268435456
bytes (256 MiB). The task's whole durable workspace is separately capped, so
several large files can pass individually and still exceed the aggregate. See
[limits](/reference/limits).

**Two files with the same name and only one arrives.** They do not collide —
duplicate basenames are disambiguated deterministically, so a second
`report.csv` becomes `report-1.csv`. Tell the agent to expect the suffixed name,
or stage with distinct filenames.

**The agent cannot find the files on disk.** Materialization happens once per
shell session. If the sandbox pod was replaced mid-task, the inputs are not
copied again, so the durable copy exists while the disk one does not. The file
tool still reads them, because it falls back to durable storage on a miss; bash
does not. Check whether the pod was reclaimed — see
[debug a failed task](/guides/tasks/debug-a-failed-task).

## Related

- [Run a command in a sandbox](/guides/sandbox/run-a-command) — using the files
- [Collect artifacts and logs](/guides/sandbox/collect-artifacts-and-logs) — getting results back
- [Limits](/reference/limits) — size ceilings
- [The file model](/concepts/sandbox/the-file-model) — why inputs are task-scoped
- [Artifacts](/concepts/execution/artifacts) — the durable store behind this
