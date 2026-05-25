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
6. Cleanup retires the sandbox session through lease/idle TTL and garbage
   collection.

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
