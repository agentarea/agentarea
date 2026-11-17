# governance: porting notes

Ports for runs: `RunPolicies.Task` (`TaskService._resolve_task_policy` with the
`execution` / `parameters.max_iterations` / approval merge of `start_run`, and
the `governance_snapshot` it stores, `libs/tasks/agentarea_tasks/task_service.py`)
and `AuditReader.ResourceEvents` (`AuditRepository.resource_events_page`, for
`GET /inbox/decisions`).

## Bugs kept

- `policies.created_at` and a policy rule's insert `updated_at`, plus `audit_events.created_at` written by `record`, hold the local wall clock (`datetime.now`, `libs/common/agentarea_common/base/models.py:14`). A rule update stamps naive UTC (`libs/governance/agentarea_governance/infrastructure/repository.py:136`). `record_once` leaves `created_at` to the database default.
- A PATCH cannot clear a field. A sent `null` reaches the enforceability check, but the repository skips `None` (`repository.py:131`). So `{"condition": null}` keeps the stored condition, and `{"target": null}` is refused with "invalid target selector None".
- A PATCH with `"effect": null` fails as a 500. Python reads `None.value` in `assert_enforceable`'s last branch (`libs/governance/agentarea_governance/domain/rules.py:400`); here it is a plain error.
- Policy audit rows (`@audited`, `libs/common/agentarea_common/audit/decorator.py:145,171`) are best-effort: a failed insert is logged and the request succeeds. Their `changes` is null. Secret audit rows propagate their failure.
- Delete removes a row of an unknown effect or subject_type that list and get hide, because delete reads the raw row (`libs/governance/agentarea_governance/application/service.py:81-84`, `apps/api/agentarea_api/api/v1/policies.py:192`).
- The prompt-injection gate (priority 300) never refuses. The pre-call context is built without content (`libs/governance/agentarea_governance/bridges/temporal_bridge.py:232`), so `api.CheckGates` runs only the cost, token and service gates.

## Not ported or not wired

- Egress exits (`api/v1/egress_exits.py`, `egress_exit_service.py`): the five `/egress-exits` routes answer 404 "egress exits need the enterprise edition" unless the `egress_exits` entry point is built (`Deps.EgressExits`). Errors render as problem+json; the `requires` 422 carries no `input`. The upstream check uses the process's netguard policy; audit rows are written in the request's transaction.
- `GET /governance/task-policy-snapshots/{task_id}` is mounted only when `Deps.Tasks` is set. It reads `tasks.metadata`, which runs owns, and runs has not provided that port yet.
- Default policies: `Module.ProvisionDefaults` implements `provision_default_policies`, but identity's `OnWorkspaceCreated` is not wired to it in `app`. Until it is, new workspaces get no baseline. `GOVERNANCE_DEFAULT_POLICIES_PATH` (read with `os.getenv` in `application/defaults.py:25`, absent from the chart and the naming guard) is `Deps.DefaultPoliciesPath`, and nothing reads the env var yet.
- Audit sink: `Deps.Sink` (the enterprise `audit_sink` forward) is not passed by `app`, because extensions are built after the modules.
- Agents' approval toggle: `AgentApprovals()` (sync in the agent write's transaction; release is
  admin-only, else `ApprovalEnforcedError`). Catalog install guard: `InstallPolicy()`
  (`domain.DecideCatalogInstall`; workspace and user layers at install, workspace only at run time).
- `tool_call_approvals` belongs to runs (dossier).
