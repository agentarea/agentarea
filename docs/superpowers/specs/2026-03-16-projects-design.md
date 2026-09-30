# Projects

**Date:** 2026-03-16
**Status:** Draft
**Scope:** Add Project entity as a scoped work environment for agents — files, default tools, and permission boundaries

## Context

Today all entities (agents, skills, MCP servers, triggers) live flat within a workspace. There's no way to group resources, scope execution, or control access beyond the workspace level. Users need a way to create isolated work environments where agents operate on specific files with specific tools.

A Project is a **place to work** — it owns files, has a description/instructions, and associates default skills/MCPs. It's also a **permission boundary** — in the enterprise version, Keto (ReBAC) relations enforce which agents, skills, and users can access a project. In the OSS version, junction tables serve as organizational metadata without enforcement.

### Analogies

- Like a GitHub repository: files, description, collaborators, settings
- Like claude-code's project context: CLAUDE.md + files + working directory
- Like a Devin session's Devbox: a workspace with files that agents operate in

## Decisions

- **Project lives inside a Workspace** — workspace is the org/team level, projects are containers within it
- **Project is optional for tasks** — no project = empty context, agent still works fine
- **Agents are workspace-level** — agents are not owned by projects. An agent can work across multiple projects. When a task runs with a project, the agent operates within that project's file space
- **Skills/MCPs are workspace-level** — projects reference which skills/MCPs are relevant via junction tables. In OSS this is organizational; in enterprise, Keto enforces it
- **Project instructions are data, not prompt injection** — the agent can read project instructions via a tool if it wants to. Nothing is auto-injected into the agent's system prompt
- **Files are just files** — no RAG, no embeddings, no semantic search. Upload files, agents read/write them with filesystem tools
- **OSS vs Enterprise permission split** — junction tables exist in both. Keto relations (ReBAC) only in enterprise. Application code is identical; the difference is whether a Keto check runs before execution
- **No file versioning** — MinIO versioning is available if needed later, but not designed around now
- **No subproject inheritance** — `parent_project_id` column exists for future nesting, but no inheritance logic now

## Data Model

### `projects` table

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK (BaseModel) |
| workspace_id | str | WorkspaceScopedMixin |
| created_by | str | WorkspaceScopedMixin |
| name | str(255) | NOT NULL |
| description | text | nullable |
| instructions | text | nullable — project context, readable by agent via tool |
| parent_project_id | UUID FK | -> projects.id, nullable, ondelete SET NULL (future nesting) |
| minio_prefix | str(500) | auto-generated: `projects/{id}/files/` |
| created_at | datetime | BaseModel |
| updated_at | datetime | BaseModel |

### `project_skills` junction table

| Column | Type | Notes |
|---|---|---|
| project_id | UUID FK | -> projects.id, ondelete CASCADE |
| skill_id | UUID FK | -> skills.id, ondelete CASCADE |

Composite PK: (project_id, skill_id)

### `project_mcp_instances` junction table

| Column | Type | Notes |
|---|---|---|
| project_id | UUID FK | -> projects.id, ondelete CASCADE |
| mcp_instance_id | UUID FK | -> mcp_server_instances.id, ondelete CASCADE |

Composite PK: (project_id, mcp_instance_id)

### `project_agents` junction table

| Column | Type | Notes |
|---|---|---|
| project_id | UUID FK | -> projects.id, ondelete CASCADE |
| agent_id | UUID FK | -> agents.id, ondelete CASCADE |

Composite PK: (project_id, agent_id)

### Task modification

Add nullable `project_id` to task creation:

| Column | Type | Notes |
|---|---|---|
| project_id | UUID FK | -> projects.id, nullable, ondelete SET NULL |

When `project_id` is set, the execution workflow syncs project files to the pod's `/workspace/` before agent execution and syncs changed files back after completion.

## MinIO Storage Layout

```
{bucket}/
  projects/{project_id}/files/        # Project files (persistent, source of truth)
    README.md
    data/input.csv
    src/main.py
    ...
  tasks/{workspace_id}/{task_id}/     # Task context (ephemeral, existing)
    outputs/{output_id}.json          # Offloaded tool outputs (existing ContextStore)
    history/chunk_{n}.json            # Compacted message history (existing ContextStore)
```

Project files are persistent across tasks. Task outputs/history are ephemeral per execution (existing behavior via ContextStore).

## Execution Architecture

> **ADR:** See `docs/adr/2026-03-19-project-sandbox-file-access.md` for the full decision record covering all options evaluated.

### Two-tier tool architecture

Tools are split into two tiers based on whether they need a pod:

| Tier | Tools | Execution |
|---|---|---|
| **Tier 1 — S3-direct** | `read_file`, `write_file`, `list_dir`, `glob`, `grep`, `get_project_info` | Python Temporal activities calling MinIO S3 API directly. No pod needed. |
| **Tier 2 — Sandboxed** | `run_script` | Stateless warm pool pod. Go activation service syncs files before/after execution. |

### Tier 1: S3-direct file tools

File tools call MinIO directly from Temporal activities using boto3 — the same pattern as `ContextStore`. No pod is claimed, no session is needed. Operations map to S3 primitives:

```
read_file(path)        → GetObject(prefix + path)
write_file(path, data) → PutObject(prefix + path)
list_dir(path)         → ListObjectsV2(prefix + path + "/")
glob(pattern)          → ListObjectsV2(prefix) + fnmatch filter
grep(pattern, path)    → GetObject → stream scan lines → return matches
get_project_info()     → reads from AgentExecutionState.project_context (loaded at workflow init)
```

`get_project_info` never hits the network at tool-call time — project info is loaded once at workflow init via `resolve_project_context` activity and stored in state.

### Tier 2: Sandboxed `run_script`

`run_script` uses the existing stateless warm pool (`FindAvailablePod` + `ExecuteInPod` + `ReturnToPool`). The warm pool pod's activation service (port 8080) gets two new endpoints:

```
POST /workspace/setup
Body: { "minio_prefix": "projects/{id}/files/", "work_dir": "/workspace/" }
→ Downloads all files from MinIO prefix to /workspace/ using Go AWS SDK

POST /workspace/teardown
Body: { "minio_prefix": "projects/{id}/files/", "work_dir": "/workspace/" }
→ Uploads all files from /workspace/ back to MinIO, then wipes /workspace/
```

`/workspace/` is an `emptyDir` volume — contains only the target project's files. `cd ../../` is harmless (nothing else is there). Isolation by construction, not policy.

Execution sequence for a single `run_script` call:

```
1. Acquire pod: FindAvailablePod
2. Setup:        POST /workspace/setup  → files synced from MinIO to /workspace/
3. Execute:      ExecuteInPod           → script runs against /workspace/
4. Teardown:     POST /workspace/teardown → changed files synced back to MinIO
5. Release:      ReturnToPool
```

**Package persistence:** packages installed to `/workspace/venv/` (Python) or `/workspace/node_modules/` (Node) live inside `/workspace/` and sync back to MinIO automatically — available on the next `run_script` call. System-level installs (`apt install`) are ephemeral. Agents that need system packages should maintain `/workspace/.agentarea/setup.sh`; the activation service runs it automatically after setup if it exists.

### Workflow router changes

Filesystem tools are a new tool category in `_process_tool_call`:

```python
# Existing branches:
# - MCP tools → _execute_mcp_tool
# - Agent delegation tools → _handle_agent_tool_call
# - Skill tools → _handle_skill_tool_call

# New branch:
# - Tier 1 tools (read_file, write_file, etc.) → _execute_s3_file_tool (new)
# - Tier 2 tools (run_script) → _execute_sandbox_tool (new)
```

### Execution flow: task with project

```
1. Task created: agent_id + project_id
2. Workflow starts on Temporal
3. Activity: resolve_project_context
   - Load project from DB (name, description, instructions, skills, MCPs)
   - Store in AgentExecutionState.project_context
4. Agent execution loop (existing, with new tool branches)
   - read_file / write_file / list_dir / glob / grep
       → _execute_s3_file_tool activity → direct MinIO S3 call
   - get_project_info
       → reads from AgentExecutionState.project_context (no network call)
   - run_script
       → _execute_sandbox_tool activity:
         FindAvailablePod → /workspace/setup → ExecuteInPod → /workspace/teardown → ReturnToPool
   - MCP tools → existing _execute_mcp_tool path
```

### Execution flow: task without project

```
1. Task created: agent_id only (project_id = null)
2. Workflow starts on Temporal
3. No resolve_project_context (skipped)
4. Agent execution loop (existing)
   - S3 file tools return "no project workspace" error if called
   - run_script works (sandboxed, but /workspace/ starts empty)
   - Agent uses only its own skills/MCPs
```

### Concurrent tasks on the same project

**Policy: last-write-wins.** Multiple tasks can run against the same project concurrently. Each gets its own session pod with its own copy of the files. On sync-back, files are written to MinIO by key — if two tasks modify the same file, the last to sync wins. This is the same model as S3 (eventual consistency, last-write-wins) and is acceptable for the initial version.

No locking, no conflict detection. If users need serial execution, they can use triggers or queue tasks manually. File-level locking can be added later if needed.

### Failure handling

- **Pod crash mid-task**: Temporal retry policy kicks in. New pod claimed, files re-synced from MinIO (source of truth). In-flight writes to `/workspace/` that weren't synced are lost.
- **Sync-back failure**: Temporal retries the sync activity. If it exhausts retries, task fails. MinIO state remains as it was before the task (clean).
- **Partial sync-back**: Sync uses MinIO's `PutObject` per file — each file is atomic. Partial sync means some files updated, some not. Acceptable for v1.

## Agent-Facing Tools

Built-in tools available during execution. Operate on `/workspace/` inside the session pod via `ExecuteInSession`. The agent doesn't know about MinIO, pods, or sync.

| Tool | Description |
|---|---|
| `read_file(path, offset?, limit?)` | Read file contents with optional line range |
| `write_file(path, content)` | Write/overwrite a file |
| `list_dir(path?)` | List directory contents, defaults to `/workspace/` |
| `glob(pattern)` | Find files matching glob pattern |
| `grep(pattern, path?, flags?)` | Search file contents with regex |
| `run_script(command, timeout?)` | Execute a shell command in the sandbox |
| `get_project_info()` | Returns project name, description, instructions from state (no pod call) |

These route through a new `_execute_workspace_tool` method in the workflow, NOT through `_execute_mcp_tool`. They are registered as tool definitions in the agent's tool list alongside MCP tools, but dispatched differently.

`run_script` uses the same `ExecuteInSession` endpoint as the other tools but passes the user's command directly. It reuses the same underlying `ExecuteRequest`/`ExecuteResponse` model that the existing sandbox handler uses.

## Models Requiring `project_id`

Files that need modification to thread `project_id` through the execution pipeline:

| File | Model/Class | Change |
|---|---|---|
| `libs/execution/.../models.py` | `AgentExecutionRequest` | Add `project_id: str \| None = None` |
| `libs/execution/.../workflows/models.py` | `AgentExecutionState` | Add `project_id: str \| None = None`, `project_context: dict \| None = None` |
| `libs/execution/.../workflows/models.py` | `ContinueAsNewState` | Add `project_id: str \| None = None` |
| `libs/tasks/.../domain/models.py` | `Task`, `SimpleTask` | Add `project_id: str \| None = None` |
| `libs/tasks/.../infrastructure/orm.py` | `TaskORM` | Add `project_id` FK column |
| `apps/api/.../api/v1/agents_tasks.py` | `TaskCreate` schema | Add `project_id: str \| None = None` |
| `libs/agents/.../domain/interfaces.py` | `StartTaskRequest` | Add `project_id: str \| None = None` |

## Temporal Activities

New activities needed:

| Activity | Purpose |
|---|---|
| `resolve_project_context` | Load project from DB (name, description, instructions, skill IDs, MCP IDs). Returns project context dict. Runs once at workflow init. |
| `execute_s3_file_tool` | Execute a Tier 1 file tool (read_file, write_file, list_dir, glob, grep) via direct MinIO S3 call using boto3. Same client pattern as `ContextStore`. |
| `execute_sandbox_tool` | Execute `run_script`: FindAvailablePod → POST /workspace/setup → ExecuteInPod → POST /workspace/teardown → ReturnToPool. |

Lifecycle: `resolve_project_context` (once at init) → [agent loop: `execute_s3_file_tool` or `execute_sandbox_tool` per tool call].

## Permission Model

### OSS (no Keto)

- Junction tables (`project_skills`, `project_mcp_instances`, `project_agents`) are organizational metadata
- Any workspace member can access any project in the workspace
- No enforcement — just "these things are associated with this project"

### Enterprise (Keto ReBAC)

Junction tables are synced to Keto relations:

```
# User access
project:{id}#viewer@user:{uid}
project:{id}#editor@user:{uid}
project:{id}#admin@user:{uid}

# Resource boundaries
project:{id}#allowed_agent@agent:{agent_id}
project:{id}#allowed_skill@skill:{skill_id}
project:{id}#allowed_mcp@mcp_instance:{mcp_id}

# Inheritance from workspace
project:{id}#parent@workspace:{ws_id}
```

At execution time, a Keto check verifies:
- User can create tasks in this project
- Agent is allowed in this project
- Each skill/MCP the agent tries to use is allowed in this project

Application code is the same — the Keto middleware intercepts and enforces.

## API Endpoints

### Project CRUD

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects` | List projects in workspace |
| GET | `/api/v1/projects/{id}` | Get project details |
| PATCH | `/api/v1/projects/{id}` | Update project |
| DELETE | `/api/v1/projects/{id}` | Delete project (and MinIO files) |

### Project associations

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/projects/{id}/skills` | Add skill to project |
| DELETE | `/api/v1/projects/{id}/skills/{skill_id}` | Remove skill from project |
| GET | `/api/v1/projects/{id}/skills` | List project skills |
| POST | `/api/v1/projects/{id}/mcp-instances` | Add MCP instance to project |
| DELETE | `/api/v1/projects/{id}/mcp-instances/{mcp_id}` | Remove MCP instance |
| GET | `/api/v1/projects/{id}/mcp-instances` | List project MCP instances |
| POST | `/api/v1/projects/{id}/agents` | Add agent to project |
| DELETE | `/api/v1/projects/{id}/agents/{agent_id}` | Remove agent |
| GET | `/api/v1/projects/{id}/agents` | List project agents |

### Project files

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/projects/{id}/files` | Upload file(s) to project |
| GET | `/api/v1/projects/{id}/files` | List project files |
| GET | `/api/v1/projects/{id}/files/{path}` | Download file |
| DELETE | `/api/v1/projects/{id}/files/{path}` | Delete file |
| POST | `/api/v1/projects/{id}/files/presigned-url` | Get presigned upload/download URL |

### Task modification

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/agents/{id}/tasks` | Add optional `project_id` field to request body |

## Frontend

### New pages

| Route | Description |
|---|---|
| `/projects` | Project list |
| `/projects/new` | Create project |
| `/projects/{id}` | Project detail — files, agents, skills, MCPs, recent tasks |
| `/projects/{id}/settings` | Project settings — name, description, instructions |

### Navigation

Add "Projects" to the main sidebar navigation, between "Agents" and "Skills".

### Project detail page

- **Overview tab**: description, instructions, stats (file count, task count)
- **Files tab**: file browser with upload/download/delete. Tree view of MinIO contents
- **Agents tab**: associated agents with add/remove
- **Skills tab**: associated skills with add/remove
- **MCP Servers tab**: associated MCP instances with add/remove
- **Tasks tab**: recent tasks executed within this project

## Existing Infrastructure Used

| Component | How it's used | What's new |
|---|---|---|
| `ContextStore` (context_store.py) | S3 client pattern for MinIO access | Project file tools follow the same boto3 pattern |
| Warm pool (warmpool/client.go) | `FindAvailablePod`, `ExecuteInPod`, `ReturnToPool` | Unchanged — stateless pattern reused as-is for `run_script` |
| Sandbox handler (sandbox_handler.go) | `executeSandbox` routes to warm pool or dev executor | Unchanged — `run_script` reuses this path |
| `ExecuteRequest`/`ExecuteResponse` | Script execution model | Reused for `run_script` sandbox execution |
| `WorkspaceScopedMixin` | Workspace scoping base | Project model inherits it |
| `RepositoryFactory` | Creates workspace-scoped repositories | Add `ProjectRepository` |
| Temporal workflow router | `_process_tool_call` dispatches to MCP/agent/skill handlers | Two new branches: S3 file tools + sandbox tool |
| `build_agent_config_activity` | Loads agent config at workflow init | `resolve_project_context` follows same pattern |

## MCP Manager Changes (Go)

Minimal changes — no session management. Only the warm pool pod's **activation service** gets two new endpoints:

```
agentarea-mcp-manager/
  activation-service/
    workspace_handler.go   # NEW — POST /workspace/setup + POST /workspace/teardown
```

Both endpoints use the Go AWS SDK (already a dependency) to sync files between MinIO and `/workspace/`:

```go
type WorkspaceRequest struct {
    MinioPrefix string `json:"minio_prefix" binding:"required"` // "projects/{id}/files/"
    WorkDir     string `json:"work_dir" binding:"required"`      // "/workspace/"
}
```

MinIO credentials are injected via pod environment variables. The endpoints run on the existing activation service port (8080) alongside existing lifecycle endpoints. No changes to `warmpool/client.go`, no session state, no new routes in the main MCP manager API.

If `setup.sh` exists at `/workspace/.agentarea/setup.sh` after file sync, the setup endpoint runs it automatically before returning — allowing projects to declare system-level dependencies.

## Acceptance Criteria

### Data model
- [ ] `projects` table created with all columns via Alembic migration
- [ ] Junction tables (`project_skills`, `project_mcp_instances`, `project_agents`) created
- [ ] `project_id` FK added to task ORM
- [ ] Project model uses `WorkspaceScopedMixin`, follows existing patterns

### API
- [ ] Project CRUD endpoints work (create, list, get, update, delete)
- [ ] Association endpoints work (add/remove/list skills, MCPs, agents per project)
- [ ] File endpoints work (upload, list, download, delete via MinIO)
- [ ] Task creation accepts optional `project_id`
- [ ] Deleting a project cleans up MinIO files

### Execution
- [ ] Task with project_id: pod claimed, files synced in, agent can read/write via workspace tools, files synced back, pod released
- [ ] Task without project_id: works as before, no pod claimed
- [ ] `read_file`, `write_file`, `list_dir`, `glob`, `grep` operate correctly on `/workspace/`
- [ ] `run_script` executes commands in sandbox and returns stdout/stderr/exit_code
- [ ] `get_project_info` returns project metadata from state without pod call
- [ ] Workspace tools route through `_execute_workspace_tool`, not `_execute_mcp_tool`
- [ ] Skill isolation: each skill gets fresh workspace, data flows through MinIO

### MCP Manager
- [ ] Session endpoints work: claim, execute, sync, release
- [ ] `SyncFiles(pull)` downloads MinIO prefix to `/workspace/`
- [ ] `SyncFiles(push)` uploads changed files from `/workspace/` to MinIO
- [ ] `ReleasePod` wipes `/workspace/` and returns pod to "waiting" state
- [ ] Dev path works without K8s (route to `SANDBOX_EXECUTOR_URL`)

### Frontend
- [ ] Projects page: list, create, detail view
- [ ] File browser: upload, download, delete, tree view
- [ ] Association management: add/remove agents, skills, MCPs
- [ ] Sidebar navigation includes Projects
- [ ] Task creation UI allows selecting a project

## Out of Scope

- Subproject inheritance (parent_project_id exists but no logic)
- File versioning
- RAG / semantic search over project files
- Real-time file watching / live sync
- Project templates
- Project-level environment variables
- Project-level secrets
- Collaborative editing / conflict resolution
- File size limits (beyond MinIO defaults)
- Concurrent task file locking (last-write-wins is acceptable for v1)
