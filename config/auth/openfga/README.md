# OpenFGA Access-Control Config

OpenFGA is the preferred graph backend for new AgentArea capability
authorization work. Keto remains supported as a fallback during migration.

- `model.fga` is the OpenFGA DSL model mirroring the current Keto namespaces.
- The `/access-control` API can operate against OpenFGA when
  `OPENFGA_ENABLED=true`.
- Graph object and user refs intentionally keep the current PascalCase names
  (`Skill:<id>`, `Agent:<id>`, `Workspace:<id>#members`) so existing API payloads
  and access-explorer data do not require an immediate data migration.

## Dev bootstrap

`docker-compose.dev.yaml` starts OpenFGA and exposes:

- HTTP API: `http://localhost:8088`
- gRPC API: `localhost:8089`
- Playground: `http://localhost:3001`

OpenFGA requires a store and authorization model before checks can run. Create
those with the OpenFGA CLI or API, then set:

```bash
OPENFGA_ENABLED=true
OPENFGA_API_URL=http://openfga:8080
OPENFGA_STORE_ID=<store-id>
OPENFGA_AUTHORIZATION_MODEL_ID=<model-id>
```

During migration, leave `KETO_ENABLED=true` as fallback for the legacy
relationship explorer until the store and model are seeded. Concrete tool
invocation authorization is fail-closed and requires either OpenFGA grants or
an explicit task policy with `tools.allowed: ["*"]`.

## Tool invocation grants

Runtime tool calls check `ToolResource:<tool>~args~<sha256>#can_call@User:<id>`.
The `<sha256>` is computed from canonical JSON args with sorted keys.

Two grant shapes are supported:

- Broad tool grant: `Tool:<tool>#callers@User:<id>`.
- Exact argument grant:
  `ToolResource:<tool>~args~<sha256>#callers@User:<id>`.

Use `/v1/tool-access/grants` to create or revoke these grants and
`/v1/tool-access/checks` to check them. Omit `arguments` for the main whole-tool
case; include `arguments` only for exact-argument exceptions.

The app sends a contextual graph relationship
`ToolResource:<tool>~args~<sha256>#tool@Tool:<tool>` during each check, so broad
tool grants do not require pre-creating every possible `ToolResource` object.
No matching relationship means deny.
