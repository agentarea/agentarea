# AgentArea Helm Chart - Initialization Order

The `agentarea` chart bundles its stateful dependencies as templates (PostgreSQL,
RustFS) and one subchart (Valkey). Ordering comes from a few Helm hooks plus
init containers and jobs that wait for the database themselves; most resources
are plain resources applied together.

## Sequence

| Phase | Resource | Mechanism |
|-------|----------|-----------|
| pre-install, weight -1 | PostgreSQL StatefulSet (`postgresql.enabled`) | Helm hook, first install only |
| pre-install/pre-upgrade, weights 0-3 | Kratos JWKS ServiceAccount, Role, RoleBinding and `kratos-jwks-init` Job (`kratos.generateJwks`) | Helm hooks |
| install/upgrade | Secrets, ConfigMaps, Services, Deployments, Valkey | plain resources |
| install/upgrade | `create-{kratos,openfga}-db` Jobs | plain Jobs; an init container polls `pg_isready`, then each creates its database if missing |
| install/upgrade | `db-migration` Job | plain Job; an init container waits for the database port, then runs `global.database.migrations.command` |
| install/upgrade | `registry-reconcile` Job (`registryReconcile.enabled`) | plain Job; waits for the database port, then syncs `registryReconcile.registries` |
| install/upgrade | Temporal | the `schema` init container waits for the database, then creates the Temporal and visibility databases if missing and updates both schemas |
| install/upgrade | `create-temporal-namespace` Job | plain Job; retries until the server answers, then creates `global.temporal.namespace` if missing |
| post-install/post-upgrade, weight 4 | `kratos-migrate`, `openfga-migrate` Jobs | Helm hooks |
| post-install/post-upgrade, weight 5 | `rustfs-bucket-init` Job | Helm hook; creates `global.storage.bucket` and its CORS rules |

The migration and reconcile Jobs set `ttlSecondsAfterFinished: 300`, so an upgrade
after that window recreates and re-runs them; both are idempotent.

## Troubleshooting

```bash
kubectl get jobs -n agentarea
kubectl logs -n agentarea job/agentarea-db-migration -c wait-for-db
kubectl logs -n agentarea job/agentarea-db-migration
kubectl logs -n agentarea job/agentarea-rustfs-bucket-init
kubectl logs -n agentarea deploy/agentarea-temporal -c schema
```

## Key files

- PostgreSQL: [templates/postgresql/statefulset.yaml](./agentarea/templates/postgresql/statefulset.yaml)
- Database jobs: [templates/jobs/](./agentarea/templates/jobs/)
- Kratos: [templates/kratos/](./agentarea/templates/kratos/)
- OpenFGA: [templates/openfga/openfga.yaml](./agentarea/templates/openfga/openfga.yaml)
- RustFS: [templates/rustfs/rustfs.yaml](./agentarea/templates/rustfs/rustfs.yaml)
- Temporal: [templates/agentarea-temporal/deployment.yaml](./agentarea/templates/agentarea-temporal/deployment.yaml)
- Valkey subchart: [Chart.yaml](./agentarea/Chart.yaml)
