# OpenFGA Access-Control Config

OpenFGA is the preferred graph backend for new AgentArea capability
authorization work. Keto remains supported as a fallback during migration.

- `model.fga` is the human-readable OpenFGA DSL model.
- `model.fga.yaml` is the FGA CLI test fixture for the model.
- `authorization-model.json` is the deployable OpenFGA HTTP API model loaded by
  the AgentArea app and worker during bootstrap. Generated from `model.fga`, not
  hand-edited:

  ```bash
  fga model transform --file model.fga > authorization-model.json
  cp authorization-model.json ../../../charts/agentarea/files/openfga/authorization-model.json
  fga model test --tests model.fga.yaml   # must pass before commit
  ```
- The `/access-control` API can operate against OpenFGA when
  `ACCESS_CONTROL_BACKEND=openfga`.
- Graph object and user refs intentionally keep the current PascalCase names
  (`Skill:<id>`, `Agent:<id>`, `Workspace:<id>#members`) so existing API payloads
  and access-explorer data do not require an immediate data migration.

## Dev bootstrap

`docker-compose.dev.yaml` starts OpenFGA and exposes:

- HTTP API: `http://localhost:8088`
- gRPC API: `localhost:8089`
- Playground: `http://localhost:3001`

`docker-compose.dev.yaml` now runs with OpenFGA by default. The API and worker
bootstrap the OpenFGA store and load `authorization-model.json` before wiring the
OpenFGA client. The default dev settings are:

```bash
ACCESS_CONTROL_BACKEND=openfga
ACCESS_CONTROL_OPENFGA_API_URL=http://openfga:8080
ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP=true
ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=true
ACCESS_CONTROL_OPENFGA_STORE_NAME=agentarea
ACCESS_CONTROL_OPENFGA_MODEL_PATH=/app/config/auth/openfga/authorization-model.json
```

`ACCESS_CONTROL_OPENFGA_STORE_ID` and
`ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID` remain optional overrides. When
`ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=true`, the model in
`ACCESS_CONTROL_OPENFGA_MODEL_PATH` wins and the returned model id is used in the
running process. This avoids stale model ids after model changes.

Concrete tool invocation authorization is fail-closed and requires OpenFGA
grants. No matching graph grant means deny.

## Helm bootstrap

The chart packages `charts/agentarea/files/openfga/authorization-model.json` as
a ConfigMap and mounts it into the backend and worker at
`/etc/agentarea/openfga/authorization-model.json`. When `openfga.enabled=true`,
the chart sets:

```bash
ACCESS_CONTROL_BACKEND=openfga
ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP=true
ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=true
ACCESS_CONTROL_OPENFGA_MODEL_PATH=/etc/agentarea/openfga/authorization-model.json
```

For managed OpenFGA, set `openfga.enabled=false` and provide the same
`ACCESS_CONTROL_OPENFGA_*` values through `backend.envVars` and `worker.envVars`.

## Tool invocation grants

Runtime tool calls check
`ToolResource:<workspace>/<tool>~args~<sha256>#can_call@User:<id>`.
The `<sha256>` is computed from canonical JSON args with sorted keys.

Two grant shapes are supported:

- Broad tool grant: `Tool:<workspace>/<tool>#callers@User:<id>`.
- Exact argument grant:
  `ToolResource:<workspace>/<tool>~args~<sha256>#callers@User:<id>`.

The OpenFGA model also requires the user to be a member of the same workspace:
`Tool#can_call` is `callers and members from workspace`, and
`ToolResource#can_call` is either the exact-argument caller intersected with the
resource workspace, or inherited from the broad tool. This keeps workspace
membership inside the graph decision instead of duplicating it as an API-side
membership check.

Use `/v1/tool-access/grants` to create or revoke these grants and
`/v1/tool-access/checks` to check them. Omit `arguments` for the main whole-tool
case; include `arguments` only for exact-argument exceptions.

The app sends a contextual graph relationship
`ToolResource:<workspace>/<tool>~args~<sha256>#tool@Tool:<workspace>/<tool>` and
workspace contextual relationships during each check, so broad tool grants do
not require pre-creating every possible `ToolResource` object. No matching
grant and workspace membership means deny.
