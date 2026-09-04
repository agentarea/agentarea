---
title: Collect artifacts and logs from a sandbox
type: guide
summary: Ask a command to copy files out of the sandbox before the pod is reclaimed, and retrieve them plus captured stdout and stderr through the API.
prerequisites:
  - /concepts/sandbox/sessions
  - /concepts/sandbox/the-file-model
related:
  - /guides/sandbox/run-a-command
  - /guides/sandbox/provide-input-files
  - /reference/limits
  - /concepts/execution/artifacts
last_updated: 2026-07-29
---

# Collect artifacts and logs from a sandbox

Do this whenever a command produces something you want after the task ends. The
sandbox filesystem is deleted with its pod, so a file that is not copied out is
gone — asking for it afterwards is not possible.

Do not use artifact collection for large intermediate files. Copy out the
deliverable, not the build tree; per-file and per-task ceilings apply, and
exceeding them fails the copy rather than truncating it.

## Prerequisites

- An agent that can run commands — see [run a command](/guides/sandbox/run-a-command)
- A configured object store behind the artifact service
- [Sessions](/concepts/sandbox/sessions) for when the sandbox disk disappears

## Steps

### 1. Name the files when running the command

The `bash` tool takes `artifact_paths`, a list of relative paths to copy out
after the command finishes. The agent supplies them; instruct it to do so:

```
Write your results to results.json, and request results.json as an artifact.
```

Paths are relative to the working directory. Absolute paths, `..` segments, and
NUL bytes are refused before the copy is attempted.

### 2. Choose how output is captured

stdout and stderr are captured with byte limits rather than being returned
whole. Two ways to get them, and they suit different sizes:

**Read them from the tool result.** Fine for ordinary command output. The result
carries the captured text along with `stdout_truncated` and `stderr_truncated`
flags so you can tell a clipped stream from a short one.

**Read them as stored references.** For anything large. A persisted execution
record does not carry inline `stdout` or `stderr` at all — those are rejected —
so the record instead holds `stdout_ref` and `stderr_ref` pointing at stored
objects. Pick this when output routinely exceeds the capture limit, because the
reference is the full stream while the inline copy is the clipped one.

### 3. Retrieve the results

List everything the task produced:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $TOKEN"
```

Each item carries an AgentArea download URL rather than an object-storage URL, so
access stays behind the platform's authorization and audit checks. Download one:

```bash
curl -s -o results.json \
  "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts/files/results.json" \
  -H "Authorization: Bearer $TOKEN"
```

## Verify

The listing is the check — an artifact that copied out appears in it with a
non-zero size and a SHA-256:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Copy-out verifies content on the way through: the executor hashes the file it
discovered, and the copy recomputes the digest over the bytes actually read,
refusing a mismatch. So an artifact present in the listing with a digest is one
whose bytes were confirmed, not merely reported.

If a requested path is missing from the listing, check the per-artifact `error`
field in the command result — a failed copy is reported there rather than
silently dropped.

## Troubleshooting

**"artifact is N bytes, over the 16777216-byte durability cap; not persisted".**
A single artifact may not exceed 16 MiB. This is deliberate: reads above that
ceiling fail at the sandbox file API anyway, so the copy is refused loudly rather
than half-completed. Compress the file, split it, or write a summary instead.
There is no streaming path for larger deliverables.

**"only N bytes remain of the 1073741824-byte task durability quota".** The task's
whole durable workspace is capped at 1 GiB, so many mid-size artifacts can each
pass the per-file check and still exhaust the aggregate. Note that input
attachments already occupy part of this quota.

**The artifact list is empty even though the command succeeded.** The command did
not request the file. `artifact_paths` is opt-in — writing a file is not enough,
the path has to be named in the same tool call. Check the event stream for
whether the agent passed `artifact_paths` at all.

**stdout looks cut off.** It was. Compare `stdout_truncated` in the result; if
true, the stream exceeded the capture limit and the stored reference holds the
rest. Capture limits are bounded at 16 MiB per stream.

**Artifacts vanished along with the task's pod.** Copy-out happens as part of the
command that requested it. A file created by an earlier command and never
requested is not retroactively collectable once the pod is reclaimed — see
[sessions](/concepts/sandbox/sessions) for the reclaim timing.

## Related

- [Run a command in a sandbox](/guides/sandbox/run-a-command) — where `artifact_paths` is passed
- [Provide input files](/guides/sandbox/provide-input-files) — the inbound direction
- [Limits](/reference/limits) — every execution and workspace ceiling in one table
- [Artifacts](/concepts/execution/artifacts) — the durable store and its history
- [The file model](/concepts/sandbox/the-file-model) — durable versus ephemeral writes
