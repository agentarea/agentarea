# Sandbox Control Plane and Data Plane

AgentArea treats sandbox execution as a data-plane capability, not as a generic
HTTP tool. OpenAPI/HTTP tools call external APIs; sandbox runtimes execute code,
skills, commands, MCP helpers, and artifact-producing jobs in an isolated
workspace.

## Boundaries

AgentArea control plane:

- owns organizations, projects, task metadata, policies, quotas, routing, and
  audit metadata;
- starts agent workflows and records high-level execution state;
- must not depend on pod names, runner URLs, or provider-specific sandbox paths;
- in hybrid/enterprise deployments, must not receive plaintext task data unless
  the customer explicitly chooses hosted execution.

Sandbox data plane:

- owns sandbox sessions, command execution, process lifecycle, logs, files,
  artifacts, snapshots, mounts, and cleanup;
- runs in AgentArea-managed infrastructure for hosted deployments;
- can run in the customer's VPC/on-prem for enterprise deployments;
- owns its secrets, object storage, egress policy, and LLM provider credentials
  when customer data residency is required.

## Production Execution Model

The production path is a durable job model:

1. The workflow asks the sandbox control plane to create a sandbox execution.
2. The control plane persists a `sandbox_execution` record and publishes a
   `SandboxExecutionRequested` event.
3. A data-plane runner claims the execution, starts the process, and emits
   status/progress events.
4. Logs and artifacts are written to data-plane storage, not returned as large
   synchronous HTTP responses.
5. The workflow waits durably for completion by signal/update or by short polling
   activities.
6. The sandbox manager owns lease renewal, idle transition, provider expiry,
   and garbage collection. Temporal does not create or destroy sandboxes.

Synchronous `/sandbox/execute` is a compatibility path for the current
AgentArea-managed K8s warm pool. The production workflow contract is the
asynchronous `/sandbox/executions` API plus data-plane runner consumption from
the durable event stream. It must not route to arbitrary executor URLs.

Current control-plane API foundation:

- `POST /sandbox/executions` creates a `sandbox_execution` record and publishes
  `com.agentarea.sandbox.execution.requested`.
- `GET /sandbox/executions/{id}` returns the control-plane state.
- `POST /sandbox/executions/{id}/events` accepts data-plane lifecycle events
  such as `claimed`, `started`, `completed`, `failed`, and output artifact
  references.
- `agentarea-sandbox-runner` consumes requested executions with a Redis consumer
  group, executes them in the configured sandbox backend, persists terminal
  state/result on the execution record, publishes lifecycle events, and
  acknowledges the request message only after the terminal state is stored.
- Agent shell and skill execution clients use `/sandbox/executions` and read
  completion from the execution record; they do not call a runner URL directly.

Events are CloudEvents-compatible JSON envelopes. In Kubernetes/dev they are
written to Redis Streams:

- `agentarea.sandbox.execution.requests`
- `agentarea.sandbox.execution.events`

A customer-hosted runner should use the same protocol: consume/claim requested
executions from the request stream using outbound connectivity from the customer
environment, execute inside the customer data plane, write logs/artifacts to
customer-owned storage, and publish lifecycle events back through the agreed
event channel.

## Runtime Replaceability

The stable contract is a sandbox runtime protocol, not a URL:

- create/resume session;
- start execution;
- read execution status;
- stream/read logs by reference;
- collect artifacts by reference;
- cancel execution;
- snapshot/restore workspace;
- pause/terminate session.

Supported runtime implementations can include:

- `agentarea-k8s`: AgentArea warm-pool runner in Kubernetes;
- `customer-runner`: customer-hosted data-plane runner that claims jobs
  outbound;
- `e2b`, `daytona`, `docker`, or other provider adapters.

Live process memory is not portable across runtimes. The portable unit is a
workspace snapshot, artifact manifest, and session metadata.

## Implemented Provider Boundary

`mcp-manager` now selects one sandbox data plane per regional deployment with
`SANDBOX_PROVIDER`. The Python worker still calls the same manager endpoints and
does not send a provider name:

- `kubernetes`, `docker`, or `agentarea` use the built-in AgentArea runtime;
- `e2b` uses an E2B-compatible lifecycle/exec/files adapter;
- `cube` uses the same E2B-compatible adapter with a separate configuration
  namespace;
- `opensandbox` uses the official OpenSandbox Go SDK.

The manager stores the task-to-provider-session binding in Redis. File staging
and the later shell execution therefore use the same sandbox even when the HTTP
manager and asynchronous runner are separate processes. Every access renews the
active-task lease (`sandboxRuntime.leaseTTL`), and an execution keeps renewing it
while a command is running.
Provider expiration is recreated on the next create-capable operation. A file
read never creates an empty replacement sandbox.

Every runtime manifest is schema v2 and includes a digest-pinned static
`agentarea-exec-supervisor` plus its non-root command uid/gid. This is an
execution invariant, not an optional provider capability:

- the provider verifies the supervisor binary through its authenticated file
  API before admitting the sandbox and again before execution;
- the supervisor runs as root, drops the task command to the declared uid/gid,
  becomes a child subreaper, and applies `RLIMIT_FSIZE`;
- it returns success only after the command has ended and `wait4(-1)` proves
  there are no descendants left, including processes that escaped their
  original process group with `setsid` or a double fork;
- a root-owned status file authenticates the supervisor digest, child exit
  code, timeout state, and quiescence;
- a missing/malformed status, transport ambiguity, or failed cleanup causes the
  manager to quarantine and delete the complete provider binding. It never
  reuses a sandbox whose process state is uncertain.

The built-in activation service uses the same supervisor. Per-file size is a
hard in-flight limit. Entry count and aggregate byte count are post-execution
audits after process quiescence; Kubernetes also constrains the workspace with
`emptyDir.sizeLimit` and the container's `ephemeral-storage` limit. No 25 ms
filesystem traversal is used as a pretend synchronous quota.

Before any external create call, the manager persists a provisioning intent and
passes its identity in provider metadata. If the create response is lost, no
replacement is allocated until provider inventory has found and removed every
matching sandbox or the bounded create interval plus remote lease has expired.
`sandboxRuntime.provisioningTimeout` bounds the create call, and
`sandboxRuntime.sessionRecordTTL` must outlive that interval plus
`sandboxRuntime.leaseTTL`.

For E2B-compatible providers that Redis record includes short-lived sandbox
access tokens. Production Redis is therefore part of the data-plane trust
boundary and must use the deployment's authenticated/encrypted storage policy.

Each external provider deployment must configure exactly one runtime manifest
and one image or template. Task and tool callers do not select a runtime or
network profile. Public internet access is one explicit deployment setting.
E2B/Cube receive it directly. OpenSandbox `egressMode=provider` sends a policy
whose default action matches that setting; `egressMode=host-public` is reserved
for the gVisor host profile, requires public access to be explicit, and sends no
provider network policy because that combination is not supported upstream.

OpenSandbox additionally requires an explicit isolation declaration. The
current production adapter accepts only `gvisor`, with a non-empty runtime
identity and digest-pinned images that the manager verifies against the host
runtime before admitting the sandbox. `kata` and `firecracker` are rejected at
startup until OpenSandbox exposes an attestation the adapter can verify. Local
Docker/runc validation is available only as `container-dev` together with
`SANDBOX_OPENSANDBOX_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT=true`. This setting is
an explicit development exception, not a production isolation claim. Do not use
the development mode for untrusted customer code.

Provider API and sandbox URLs require HTTPS. Plain HTTP is accepted only through
the corresponding explicit `allowInsecure` Helm value for local validation.
OpenSandbox's Docker runtime also requires `secureAccess=false`; AgentArea
accepts that explicit mode only with `useServerProxy=true`. Workload ports stay
bound to the data-plane loopback interface, while lifecycle and proxied exec/file
traffic remain behind the authenticated OpenSandbox API.

The equivalent Helm surface is `sandboxRuntime`. Credentials are accepted only
through provider-specific Secret references. The same rendered environment is
injected into both `mcp-manager` and `mcp-sandbox-runner`, so they cannot select
different providers accidentally.

Infrastructure requirements are provider-side, not Python requirements:

| Mode | Where code runs | Cluster/host requirement |
| --- | --- | --- |
| `e2b` hosted | E2B data plane | no KVM or sandbox runtime in the AgentArea cluster |
| `cube` self-hosted | Cube data plane | KVM-capable worker hosts for its microVM runtime |
| `opensandbox` + `gvisor` | OpenSandbox hosts | `runsc`; KVM is not required |
| `opensandbox` + `kata`/`firecracker` | not currently accepted by AgentArea | future adapter work requires verifiable runtime attestation; KVM-capable hosts alone are insufficient |
| `opensandbox` + `container-dev` | local Docker host | no KVM, but no production-grade kernel boundary |

Retirement is a data-plane concern. The manager renews the active lease while a
command or file operation is in progress and moves an inactive binding to the
deployment's idle lease. Provider expiry and reconciliation remove it without a
Temporal activity or workflow callback. A later demand creates a fresh sandbox
and the manager rehydrates committed `inputs/` entries from the immutable S3
manifest. Intermediate files disappear unless the agent explicitly publishes
them as artifacts. Full-workspace archive/restore and its retention GC are not
implemented.

## Enterprise Deployment Modes

Hosted AgentArea:

- control plane and data plane run in AgentArea infrastructure;
- customer data may be visible to AgentArea systems according to product policy.

Hybrid customer data plane:

- AgentArea SaaS owns account, billing, project metadata, policy, and optional
  observability;
- customer VPC runs workers, sandbox runners, MCP/connectors, object storage,
  secrets, egress controls, and LLM provider access;
- customer runner connects outbound to claim work or subscribes to a
  customer-owned queue;
- plaintext task data, files, tool outputs, secrets, and artifacts remain in the
  customer data plane.

Fully customer-hosted:

- API, worker, Temporal, sandbox manager, storage, secrets, runners, and LLM
  access all run in the customer environment;
- AgentArea may provide license/update channels and optional redacted telemetry.

## Non-Goals

- Do not expose `SANDBOX_EXECUTOR_URL` or any direct runner URL as the production
  extension point.
- Do not use OpenAPI/HTTP tool execution as a sandbox runtime abstraction.
- Do not put raw stdout, large logs, files, or artifacts in workflow history or
  control-plane event payloads.
- Do not claim data residency when hosted workers, hosted sandbox runners, or
  hosted LLM proxy receive plaintext task data.
