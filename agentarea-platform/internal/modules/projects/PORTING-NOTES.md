# projects: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/projects.md`.

## Kept bugs

- `list` has no ORDER BY; pages over an unordered scan can skip or repeat rows
  (`libs/projects/agentarea_projects/infrastructure/repository.py:68`).
- `created_at`/`updated_at` are the API process's naive local wall clock, not
  UTC and not the DB default (`libs/common/agentarea_common/base/models.py:14-16`).
- Name is not unique, despite the docstrings.
- The cycle check and the PATCH write are separate, unlocked transactions, so two
  concurrent PATCHes can still build a cycle
  (`libs/projects/agentarea_projects/application/service.py:48-103`).
- PATCH checks the parent (404 / 400) before it knows the project exists, so a
  foreign project with a bad parent answers the parent's error
  (`application/service.py:48-66`).
- Deleting a project orphans its files under `projects/<id>/`; nothing sweeps them.
- PATCH does not strip `name`; only create's validator does
  (`libs/projects/agentarea_projects/schemas/dto.py:51`).
- Links to children another workspace owns are hidden on read, not removed.

## Deviations

- FastAPI parses a JSON body before running dependencies, so malformed JSON
  answers 422 even to a caller without credentials. In Go the workspace edge
  authenticates first (401/403), then validates.
- The MCP toolset surface (`apps/api/agentarea_api/tools/projects_toolset.py`) is
  not ported.

## Run instructions (`api.RunInstructions`, `service/instructions.go`)

Python: `application/service.py` `run_instructions`, `repository.py` `project_ids_of_agent`/`get_instructions`,
`activities/agent/config.py` `_with_project_instructions`.

- `Chain(ws, agentID, projectID)`: the run's project (or the agent's only project; several or none give
  nothing), then each parent, root first, trimmed, empty ones skipped; a missing project or a repeat ends
  the walk. A projectID that is no UUID is `ErrInvalidProject`.
- `Blocks` renders each as `<project name="...">\ntext\n</project>` (name escaped as `html.escape`);
  runs wraps them in `<project_instructions>`. New query `AgentProjectIDs` (ordered by project id).

### Wiring needed (app, not done here)

- `runInstructionsPort{p: m.projects.RunInstructions()}` in `newRunDefinitions`:

```go
type runInstructionsPort struct{ p projectsapi.RunInstructions }

func (r runInstructionsPort) ProjectInstructions(ctx context.Context, p runsservice.Principal, projectID string) ([]string, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	out, err := r.p.Blocks(ctx, ws, p.AgentID, projectID)
	if errors.Is(err, projectsapi.ErrInvalidProject) {
		err = errors.Join(runsservice.ErrNotFound, err)
	}
	return out, err
}
```

## Platform list page (2026-11-15)

`PlatformTools.List` refuses a limit or offset outside 0..MaxInt32 instead of
letting `int32()` wrap it.
