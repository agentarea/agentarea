# OpenFGA authorization model

The platform's authorization model. It ships inside the package, so the image
applies the model its own code checks; no deployment mounts or syncs a copy.

- `model.fga` is the `agentarea` module, the DSL source of truth.
- `fga.mod` is the modular-model manifest (schema 1.2) that lists it.
- `model.fga.yaml` is the FGA CLI test fixture.
- `authorization-model.json` is the HTTP API payload the API and worker apply at
  startup. Generated, never hand-edited:

  ```bash
  fga model transform --file fga.mod > authorization-model.json
  fga model test --tests model.fga.yaml   # must pass before commit
  ```

With `AGENTAREA_AUTHZ_FGA_BOOTSTRAP=true` and `AGENTAREA_AUTHZ_FGA_APPLY_MODEL=true`
the process finds or writes this model in the store and pins its id for its
lifetime.

A deployment that adds its own types or relations builds a model from its own
`fga.mod` (this `model.fga` plus its module) and sets
`AGENTAREA_AUTHZ_FGA_MODEL_PATH` to it. The process refuses to start if that
model drops or redefines anything declared here. See
`docs/guides/governance/model-a-custom-relation.md`.
