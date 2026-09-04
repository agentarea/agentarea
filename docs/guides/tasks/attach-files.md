---
title: Attach files to a task
type: guide
summary: Upload a file with a checksum-bound presigned PUT, then reference the returned staging ref when you create the task so the agent finds it in its workspace.
prerequisites:
  - /guides/tasks/start-a-task
related:
  - /guides/tasks/retrieve-artifacts
  - /concepts/execution/artifacts
  - /concepts/sandbox/the-file-model
last_updated: 2026-07-29
---

# Attach files to a task

Do this when the agent needs to read a file you supply — a CSV to analyse, a PDF
to summarise, a log to search. Do not do this for files that should persist
across tasks; those belong in workspace or project storage, which the agent
reaches through a different path.

Uploading is a two-step: stage the bytes, then reference the staging ref in the
create-task body. There is no multipart task-create endpoint.

## Prerequisites

- An API key with access to the workspace.
- The agent id you will run the task against.
- The file's SHA-256 digest, in both hex and base64. You compute this before
  uploading; the object store verifies against it.

## Choose an upload path

| Option | Pick it when |
|---|---|
| `POST /v1/files/upload-url` then PUT to the object store | Default. Bytes go straight to storage and never transit the API process. |
| `POST /v1/files` with `purpose=attachment` | The client cannot reach the object store directly, or the file is small and you want one round trip. |

Both return a `ref` of the form `staging/{id}/{filename}`, and the create-task
endpoint treats them identically.

## Steps

### 1. Compute the digest

```bash
FILE=report.csv
SHA_HEX=$(shasum -a 256 "$FILE" | cut -d' ' -f1)
SHA_B64=$(printf '%s' "$SHA_HEX" | xxd -r -p | base64)
SIZE=$(wc -c < "$FILE" | tr -d ' ')
```

### 2. Mint a presigned upload URL

The request takes the digest as lowercase hex.

```bash
curl -s -X POST "$AGENTAREA_URL/v1/files/upload-url" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"filename\": \"$FILE\",
    \"content_type\": \"text/csv\",
    \"sha256\": \"$SHA_HEX\",
    \"size\": $SIZE
  }"
```

```json
{
  "ref": "staging/8c1f4e2a9b7d4c3e8f1a2b3c4d5e6f70/report.csv",
  "upload_url": "http://localhost:9000/artifacts/workspaces/ws-1/staging/...&X-Amz-Signature=...",
  "expires_in": 3600
}
```

### 3. PUT the bytes

The digest is bound into the signature, so the `x-amz-checksum-sha256` header is
mandatory and must carry the **base64** digest. `Content-Type` must match what
you presigned with.

```bash
curl -s -X PUT "$UPLOAD_URL" \
  -H "x-amz-checksum-sha256: $SHA_B64" \
  -H "Content-Type: text/csv" \
  --upload-file "$FILE"
```

The object store rejects a body that does not hash to the declared digest, so a
truncated or swapped upload fails here rather than reaching the agent.

**Alternative — server-proxied upload.** One call, no digest arithmetic:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/files" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -F "purpose=attachment" \
  -F "file=@report.csv"
```

```json
{
  "ref": "staging/3d9a.../report.csv",
  "filename": "report.csv",
  "size": 20481,
  "sha256": "9f86d081884c7d65...",
  "content_type": "text/csv"
}
```

### 4. Create the task with the ref

```bash
curl -s -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/sync" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Summarise the trends in report.csv.",
    "attachments": ["staging/8c1f4e2a9b7d4c3e8f1a2b3c4d5e6f70/report.csv"]
  }'
```

The server HEADs each ref to resolve its verified digest, size, and content
type, then server-side copies it into the task workspace at
`inputs/attachments/{filename}`. The agent is told about the files by relative
path in its prompt, so it can read them without being asked to fetch anything.

Two attachments with the same basename are disambiguated deterministically:
`report.csv` and `report-1.csv`.

## Verify

List the task's files and confirm the attachment landed under
`inputs/attachments/`:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.[] | {path, size, content_type}'
```

```json
{
  "path": "tasks/3f2a8c11-.../workspace/inputs/attachments/report.csv",
  "size": 20481,
  "content_type": "text/csv"
}
```

If the path is present with the size you uploaded, the agent can read it.

## Troubleshooting

**403 or `SignatureDoesNotMatch` on the PUT.** The `x-amz-checksum-sha256`
header was omitted, or carries hex instead of base64, or the `Content-Type` sent
differs from the one presigned. All three are part of the signature. Re-mint the
URL if you need to change the content type.

**404 "attachment ref not found" at task creation.** The presigned URL expired
before the PUT completed (`expires_in` is 3600 seconds), or the PUT failed and
was not retried. Mint a fresh URL and upload again — refs are not reusable
across a failed upload.

**422 "attachment integrity digest is unavailable".** The staged object carries
neither the `sha256` metadata nor an S3-native checksum. This happens when bytes
were written to the staging key by something other than these two endpoints. Do
not work around it; re-upload through a supported path.

**413 on upload or on task creation.** The per-file limit is 256 MiB, enforced
at both the presign step and the server-proxied upload. A 413 at task creation
instead means the workspace's total quota would be exceeded by the attach.

**422 "Invalid attachment ref".** Refs must begin with `staging/`. A workspace
file path is not an attachment ref; upload it with `purpose=attachment` to get
one.

**The task dispatches but the agent says it cannot find the file.** Check that
the descriptor path starts with `inputs/attachments/` in the artifacts listing.
The prompt only advertises attachments under that exact prefix, so a file
committed elsewhere in the workspace is present but not announced.

## Related

- [Start a task](/guides/tasks/start-a-task)
- [Retrieve task artifacts](/guides/tasks/retrieve-artifacts)
- [Artifacts](/concepts/execution/artifacts)
