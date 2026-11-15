# sandbox: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/sandbox.md`.

## Done

HTTP: all 11 routes (`/files` x10, `/sandboxes`). Ports for other modules in `api/`:
`Files` (projects' file routes, wired in app), `Runtime` (shell tool, sandbox file store,
completion barrier, runtime manifest), `TaskWorkspace` (manifest repository: put, attach, import
prefix, get, exists), `Inventory`, `TaskFiles` (runs' task artifact and live-file routes:
`agents_tasks.py:1498-1866` manager reads, and `agentarea_tasks/harness.py` `HarnessFiles.list/get` for
runner tasks; errors are `*api.TaskFileError` carrying Python's status and detail), `Files.Head`
(a staged object's digest, size and type for runs' attachment staging: `ArtifactStore.head`). Config: `AGENTAREA_MCP_MANAGER_URL`,
`AGENTAREA_SANDBOX_{INSPECT,FILE,CONTROL}_SECRET`, `AGENTAREA_S3_ARTIFACTS_BUCKET` (Python's names).

## Fixed Python bugs

- A download of an object with no `sha256` metadata was a 404 (`libs/common/agentarea_common/artifacts/service.py:318`);
  it is now served, checked against its size only. A digest that is present and wrong is still a 404.
- `artifact_events.created_at` was the process's naive local wall clock but read back as UTC
  (`libs/common/agentarea_common/base/models.py:14-16`); events are now stamped in UTC.
- History was by exact path and lost everything before a move (`apps/api/agentarea_api/api/v1/files.py:556`);
  a move now carries the source's events to the destination in the same transaction as the `moved` event.
- A folder move copied and deleted key by key, so a failure mid-way split the folder (`files.py:452-459`);
  it now copies every file first and, if a copy fails, deletes the copies and leaves the source whole.
  Sources are deleted only after all copies exist, so a later failure leaves duplicates, never a loss.
- A manager error answer whose body failed mid-read escaped `_stream_manager_download` as a 500
  (`apps/api/agentarea_api/api/v1/agents_tasks.py:1610-1611`); it is now 503 "Sandbox file access is
  temporarily unavailable", as the buffered path already answered.

## Kept bugs

- `upload-urls` records `created`/`modified` when the URL is minted, not when the upload lands
  (`libs/common/agentarea_common/artifacts/service.py` `authorize_put`). The bytes go from the client
  straight to S3: the webapp (`src/lib/presigned-upload.ts`) and the CLI (`source/commands/filesSync.ts`)
  make no API call after the PUT and S3 has no callback, so the API cannot see the upload land. A fix
  needs a completion route both clients call, or bucket notifications.
- Error mapping differs per route, as in Python: a reserved path is 400 on delete, 404 on read,
  422 on write; read-only `apps/` is 403 everywhere (`files.py:463-645`).

## Deviations

- `version:` object identities are accepted but not pinned: `kernel/blob` has no object versions, so a
  read compares ETags only (Python passes `VersionId`, `artifacts/workspace.py:341`).
- Content types come from Python 3.14's built-in mimetypes table; `/etc/mime.types` is not read.
- Not ported, no caller in Go yet: `list_task_ids`, `checkout_for_execution`, `release_execution_lease`,
  `SandboxFileStore.delete`, the MCP `workspace_files` toolset (ported with connections), the task
  live-file and artifact routes in `agents_tasks.py` (runs mounts them over `TaskFiles`).
- `TaskFiles` timeouts are httpx's per-operation ones (30 s, 300 s streaming) as an idle timer on the
  exchange, not a total deadline; redirects are not followed, as httpx does not.
- `TaskFiles` artifact `created_at` takes RFC 3339 (any pydantic separator; no offset = UTC) or null;
  pydantic's unix-number form is refused (the manager writes RFC 3339).
- `Download.Header`'s Content-Type carries Starlette's `; charset=utf-8` for `text/*`.
- Harness files read `Deps.Harness` (AGENTAREA_S3_BUCKET, `blob.Client.Default()`); app must pass it, a nil
  store fails the harness calls loudly.
- `/files/{file_path:path}` takes chi's `*` decoded: one trailing `%0A` is dropped, any other newline is
  a 404 `Not Found`, as Starlette's `.*$` route regex does.
- `GET /sandboxes` returns 503 when `AGENTAREA_SANDBOX_INSPECT_SECRET` is unset, as Python does.

## Run inputs (`api.RunInputs`, `service/run_inputs.go`)

Python: `activities/agent/config.py` `_prepare_task_files`, `_prepare_trigger_event_file`; `trigger_event_file.py`.

- Selected paths (≤100, canonical, not `staging/`, `.trash/`, URLs; `tasks/<uuid>/workspace/<rel>` reads
  that task's workspace) are copied to `inputs/attachments/selected-<sha16(source)>-<name>` under the
  lease `task-inputs-<task>`, once: a retry reuses the committed copy. The trigger event (name
  `trigger-event(-N).json`) is written once as indent-2 JSON, keys sorted. Every refusal wraps
  `ErrInputRefused`; storage failures are returned as they are (retried).
- Not carried: the `{"source": "task_selection"|"trigger_event"}` provenance (`PutFiles` takes none).
- Runs reads the prompt's attachment list from task metadata `workspace_attachments`; Python also
  appended the selected files there at config time (`config.py:556`). That is runs' to do with `cfg.Inputs`.

### Fixed Python bugs

- A selected workspace file stored without `sha256` metadata was "Selected task file is unavailable"
  (`config.py:301`); it is taken, checked by size, as downloads already are. Test:
  `TestRunInputsTakeAFileWithoutADigest`.

## Processors (`api.Processors`, `service/processors.go`)

Python: `apps/worker/agentarea_worker/processor_sandbox.py` `SandboxCodeRunner`.

- One signed `POST /sandbox/executions` in the processor's session (`task_id` = session) with
  `stdout_max_bytes` and `stderr_max_bytes` 4096, the shell's wait/cancel loop, stdout read from its ref,
  stderr only when the exit code is not 0; the timeout is rounded up to whole seconds, plus 30 s grace.
  Every failure wraps `ErrProcessorUnavailable`.

### Wiring needed (app, not done here)

- `newRunDefinitions(..., runInputsPort{i: m.sandbox.RunInputs()})` and streams'
  `Processors: processorRunner{p: m.sandbox.Processors()}` (`streamsPlumbing.Processors`):

```go
type runInputsPort struct{ i sandboxapi.RunInputs }

func (r runInputsPort) Inputs(ctx context.Context, p runsservice.Principal, req runsservice.InputsRequest) ([]runsapi.InputFile, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	in, err := r.i.Prepare(ctx, ws, sandboxapi.RunInputsRequest{TaskID: req.TaskID, UserID: p.UserID, Paths: req.FileIDs,
		TriggerEvent: req.TriggerEvent, TriggerEventFileName: req.TriggerEventFileName})
	if errors.Is(err, sandboxapi.ErrInputRefused) {
		return nil, errors.Join(runsservice.ErrRefused, err)
	}
	if err != nil {
		return nil, err
	}
	out := make([]runsapi.InputFile, len(in))
	for i, f := range in {
		out[i] = runsapi.InputFile{Path: f.Path, Kind: f.Kind, SHA256: f.SHA256, Size: f.Size}
	}
	return out, nil
}

type processorRunner struct{ p sandboxapi.Processors }

func (r processorRunner) Run(ctx context.Context, ws, session, command string, timeout time.Duration, max int) (streamsservice.CodeRun, error) {
	run, err := r.p.Run(ctx, ws, session, command, timeout, max)
	if err != nil {
		return streamsservice.CodeRun{}, errors.Join(streamsservice.ErrProcessorRuntimeUnavailable, err)
	}
	return streamsservice.CodeRun(run), nil
}
```
