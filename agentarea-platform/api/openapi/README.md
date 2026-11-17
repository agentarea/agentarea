# api/openapi

Generated, do not edit. `make generate` rewrites it; `make openapi-fresh` (part of `check`) fails when a regeneration would change a file.

Pipeline (`tools/openapigen`, no Python): `agentarea-webapp/src/api/openapi.json` is preprocessed in memory (unique operation ids, `{}` bodies as `json.RawMessage`, top-level `anyOf [$ref, null]` collapsed, one module tag per operation, `x-omitempty: false` on optional nullable properties so unset fields serialize as `null` like FastAPI), then oapi-codegen v2.8.2 (pinned in the tool, run through `go run ...@v2.8.2`) writes `<module>/api.gen.go` with models, chi-server and strict-server for the 12 modules.

Operation to module: `tools/openapigen/routes.json` (operation id to Python router file, from the route inventory) and the router-to-module table in `tools/openapigen/preprocess.go` (ownership map of the first wave brief). `GET /` and `GET /health` have no owner and live in `insights`.

Shared models: each package carries its own copy of the schemas its operations use (about 3.5 MB in total). The generated server code names types unqualified, so one shared models package would need import mappings and a second generation pass for no gain: these types are wire types, and a module reaches another only through its `api` package with hand-written types (layout rule 1), so a copy never crosses a module boundary. Duplicated schemas are identical because they come from one spec, and drift is caught by `openapi-fresh`.

Not generated: the 18 `{x:path}` routes and the 13 out-of-spec routes are registered by hand on the chi router; error bodies are RFC 9457 `problem+json` written by `kernel/httpx` through the generated `ErrorHandlerFunc` hooks.
