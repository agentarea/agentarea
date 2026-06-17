# OpenFGA ReBAC config

OpenFGA is the preferred graph backend for new AgentArea capability
authorization work. Keto remains supported as a fallback during migration.

- `model.fga` is the OpenFGA DSL model mirroring the current Keto namespaces.
- The existing `/rebac` API can operate against OpenFGA when
  `OPENFGA_ENABLED=true`.
- Tuple object and user refs intentionally keep the current PascalCase names
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

During migration, leave `KETO_ENABLED=true` as fallback until the store and
model are seeded.

## Tool invocation grants

Runtime tool calls check `ToolResource:<tool>:args:<sha256>#can_call@User:<id>`.
The `<sha256>` is computed from canonical JSON args with sorted keys.

Two grant shapes are supported:

- Broad tool grant: `Tool:<tool>#callers@User:<id>`.
- Exact argument grant:
  `ToolResource:<tool>:args:<sha256>#callers@User:<id>`.

The app sends a contextual tuple
`ToolResource:<tool>:args:<sha256>#tool@Tool:<tool>` during each check, so broad
tool grants do not require pre-creating every possible `ToolResource` object.
No matching tuple means deny.
