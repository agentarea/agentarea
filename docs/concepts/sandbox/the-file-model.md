---
title: The file model
type: concept
summary: An agent sees three file surfaces — the organization's context store, its own task workspace, and the ephemeral sandbox disk — each with different scope and different write rights.
prerequisites:
  - /concepts/sandbox/sessions
related:
  - /concepts/sandbox/why-a-sandbox
  - /concepts/execution/artifacts
  - /concepts/sandbox/isolation
  - /concepts/governance/authorization-basics
last_updated: 2026-07-29
---

# The file model

An agent reads and writes files across three surfaces, and they are not
interchangeable. One holds the organization's durable knowledge and the agent may
only read it. One is the agent's own deliverable surface, scoped to its task. One
is the disk inside the sandbox, which disappears when the sandbox does.

Keeping them distinct is what stops an agent from overwriting curated
organizational content as a side effect of doing its work, and what stops one
task from reading another's files.

## The problem

"The agent needs files" hides three different requirements that pull in opposite
directions.

The agent needs **context it did not produce** — documentation, policies,
reference material that belongs to the organization and outlives any task. That
content is curated. An agent that can write to it can corrupt it, and a bad edit
made by a model at 3am is discovered weeks later by someone reading the wrong
version of a policy.

The agent needs **somewhere to put results** that a user can retrieve after the
task ends. That has to be durable and it has to be attributable to the task that
produced it.

The agent needs **a working disk** — somewhere to check out a repository, install
dependencies, and write intermediate files. That is high-churn, large, and
worthless once the work is done.

Collapsing these into one store fails in a specific way. If the shell tool and
the file tool write to different places, code the agent saves is invisible to the
commands it runs, and the task stalls — the agent writes `script.py`, runs
`python script.py`, and gets "file not found". This is not hypothetical; it is
the failure the current design was built to fix.

## How AgentArea approaches it

Three surfaces, described in the code as tiers.

| Surface | Scope | Agent may | Survives the task |
|---|---|---|---|
| Organization context store | Workspace | Read | Yes |
| Task workspace | Workspace + task | Read and write | Yes |
| Sandbox filesystem | The task's pod | Read and write | No |

**The organization context store is read-only by construction.** The toolset that
exposes it offers `list_context` and `read_context` and nothing else — there is
no write or delete method to call. This is a property of the tool surface rather
than a permission check that could be misconfigured. Writing to org context is a
separate, explicit capability, so the sandbox never mutates it as a side effect.

**The task workspace is content-addressed and scoped by both workspace and
task.** Objects live under a key built from the workspace ID and task ID:

```
<prefix>/workspaces/<workspace_id>/tasks/<task_id>/objects/<sha256>
<prefix>/workspaces/<workspace_id>/tasks/<task_id>/manifests/<generation>-<sha256>.json
<prefix>/workspaces/<workspace_id>/tasks/<task_id>/current.json
```

Every object reference is checked against that prefix before it is used. The
check compares the full key against the one key the task is allowed to touch, and
it runs *before* any transfer URL is signed — a manifest that points at another
task's object is rejected with "workspace object is outside the authorized task
prefix", and the signer is never called. Cross-task reads fail at the control
plane rather than at the storage layer.

Object identity is the content hash. An entry must carry a size, a lowercase
SHA-256, and a version or ETag, and its URI must end in `/objects/<that same
hash>`. A reference whose URI and digest disagree is malformed and rejected.

Paths are normalized before use: absolute paths, backslashes, `..` traversal, and
paths that are not already in canonical form are all refused rather than cleaned
up. Rejecting rather than normalizing means a path that looks odd never silently
becomes a different, valid path.

**The sandbox filesystem is what the shell sees.** The file tool writes through
the control plane's `/sandbox/files` endpoint to the pod's `/workspace`, which is
the same filesystem bash runs against. That is what keeps the file tool and the
shell tool coherent.

### Writes go to two places

A file the agent saves is written to the sandbox disk and then written through to
the durable task workspace. Reads come from the sandbox disk, because that is the
live state the shell is also changing.

The write-through leg fails loudly. If the durable write fails, the tool raises
rather than reporting success, on the reasoning that a deliverable the user
cannot reach is a silent loss.

Reads fall back to the durable workspace when the sandbox returns 404. That
covers task inputs which are materialized onto the sandbox disk lazily: the agent
can read an input file whether or not a shell command has run yet.

### Concurrency is explicit, not last-write-wins

The task workspace is versioned. Each commit carries a generation, the generation
it was based on, and a fencing token, and the pointer to the current manifest is
updated conditionally. A commit built on a stale base fails with a workspace
conflict rather than overwriting whatever landed in between.

Transfer URLs are deliberately excluded from the durable identity. The manifest
reference that travels through Redis and workflow payloads carries no
credentials; signed URLs are generated at activation time and are valid for a
single short-lived request.

## Why not one shared filesystem for everything

A single mounted volume that all tasks and the org store share is the smallest
possible design. No manifests, no content addressing, no write-through, and the
shell and file tools are trivially coherent because there is only one disk.

It gives up the two properties that matter most here. Task isolation disappears —
any task can read and overwrite any other task's files, and the "outside the
authorized task prefix" check has nothing to enforce, because there are no
prefixes. And the org store becomes writable by anything that can write a file,
so an agent can corrupt curated content by accident.

It also does not survive the sandbox being ephemeral. The whole point of
reclaiming pods is that their disks go away, and a design whose durability story
is "the volume is still there" cannot reclaim anything.

## Why not make the org store writable by agents

Agents accumulate useful knowledge, and letting them write it back is how a
system gets better over time. The argument for it is real.

The platform's position is that writing to shared organizational memory is a
different act from doing a task, and should be a different, explicit capability
rather than an ambient side effect of having file tools. An agent with ambient
write access to org context can be steered into corrupting it by the same prompt
injection that would otherwise only have cost one task. Because the org store is
what every future task reads, a bad write there is persistent and affects work
that has nothing to do with the compromised task.

The cost is that there is currently no supported path for an agent to contribute
to org context; that has to go through whatever process writes the store
directly.

## Limits

**There is no per-user file surface.** Scoping is by workspace and by task. Two
users working in the same workspace read the same organization context, and there
is no `{user_id}` prefix in the workspace repository's key layout. A per-user
memory surface is not part of the current model.

**The org context store is workspace-wide, with no narrowing below that.** Any
task in a workspace can read everything in that workspace's context store. There
is no per-agent, per-user, or per-task restriction on which context files are
visible, so anything placed there is readable by every agent that runs in the
workspace.

**When the sandbox file API is unavailable, writes become durable-only and the
shell cannot see them.** If the control plane returns 503 — for example on a
backend with no per-task file routing — the file tool writes only to the durable
task workspace and reports success. The file is retrievable by the user but is
not on the disk bash runs against, which reproduces exactly the invisibility
problem the write-through design exists to prevent. The agent gets no signal that
this happened.

**Nothing written only by a shell command is durable.** Write-through applies to
the file tool. A file created by `bash` and never collected as an artifact lives
on the sandbox disk and is deleted with the pod. See
[sessions](/concepts/sandbox/sessions) for when that happens.

**Within a task, there is no separation between surfaces on disk.** The sandbox
filesystem is one namespace. Task inputs, agent-authored files, and intermediate
build output share it, and the prefix guarantees described above apply to the
durable store, not to paths inside the pod.

**The path checks are not shared between the two tools.** The org context toolset
applies its own simpler check for absolute paths, backslashes, and `..`
components, separate from the workspace repository's normalization. They agree
today on what they reject, but they are separate implementations rather than one
enforcement point.

## Related

- [Sessions](/concepts/sandbox/sessions) — when the sandbox disk disappears
- [Artifacts](/concepts/execution/artifacts) — how task output is collected and served
- [Isolation](/concepts/sandbox/isolation) — the boundary around the filesystem
- [Authorization basics](/concepts/governance/authorization-basics) — how workspace
  scoping is enforced elsewhere
