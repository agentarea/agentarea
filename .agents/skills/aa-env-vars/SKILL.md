---
name: aa-env-vars
description: Add, rename or remove an AgentArea environment variable. Use whenever a diff touches a pydantic settings class, os.getenv / os.Getenv / process.env, charts/agentarea/config.yaml, a docker-compose file, .env.example or a workflow env block, or when reviewing such a diff. Covers whose name it is, how to name it, where it must be wired, and what proves it.
---

# AgentArea environment variables

A variable is a contract with whoever deploys us. The name is the contract; the
Python attribute behind it is internal and can change any time. So the name is
decided once, carefully, and `scripts/check_env_naming.py` holds it in CI.

## 1. Whose name is it

Name it after **whoever reads it**.

- **A library or image reads it itself, by a real cross-tool standard**: use that
  standard's name and add it to `WHITELIST` in the guard. Today: `OTEL_*` (OTel
  SDK), `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` / `TEMPORAL_API_KEY` /
  `TEMPORAL_TLS_*` (Temporal envconfig), `KUBECONFIG`, `POSTGRES_*` for the
  postgres *image*, `AWS_*` for the AWS SDK, `NEXT_PUBLIC_*`, `PORT` / `HOST`.
- **Our code reads it and passes the value on**: ours, `AGENTAREA_`-prefixed.
- Not a standard: libpq `PG*` (drivers apply them silently) and `AWS_*` for our
  S3 storage (that is RustFS/Timeweb, while LiteLLM reads `AWS_*` for Bedrock in
  the same process). Both stay `AGENTAREA_DB_*` / `AGENTAREA_S3_*`.

## 2. How to name ours

`AGENTAREA_<DOMAIN>_<KEY>`. The guard rejects anything else.

- At most 40 characters, at most three segments after the domain, no `__`.
- The domain comes from the closed `DOMAINS` list in the guard, and is a whole
  word (`SANDBOX`, `TEMPORAL`, `TRIGGER`). Only established acronyms are short
  (`DB`, `S3`, `K8S`, `MCP`, `OTEL`, `AUTHZ`). A new domain is a decision: add it
  to `DOMAINS` and to the list in `docs/self-host/configuration.md`.
- Pick the domain by what the setting is about, not by who happens to read it:
  the outbound URL policy is `HTTP` even though MCP code reads it.
- Units go in the value, not the name: `AGENTAREA_TEMPORAL_SHUTDOWN_GRACE=120s`,
  parsed with `config/duration.py`'s `Duration`. No `_SECONDS` / `_MS`.

## 3. One owner, one source

- One thing, one variable. Never a URL *and* its parts, never a second name for
  the same value. (Two Go services once read the DB URL and its parts with
  opposite precedence.)
- No aliases, no fallback to an old name. A rename is breaking on purpose, and it
  goes in the migration table.
- Config without which the process cannot work has no default: fail at startup,
  and name the variable in the error.

## 4. Wire it

**Python.** Put the field on the settings class whose `env_prefix` is the domain
(`DatabaseSettings` → `AGENTAREA_DB_`). The env name is always `env_prefix` plus
the field name. Never `validation_alias`: the guard fails on it. A field that
belongs to another domain moves to that domain's class. Constructors and test
stubs take the *field* name (`DatabaseSettings(HOST=…)`). `extra="ignore"` drops
a wrong kwarg without a word, so check the test really sets what it means to. No
`getattr(settings, "NAME", default)`: a renamed attribute then silently becomes
the default.

**Go / TypeScript.** Read it through the service's config loader or a named
`const`, so the guard can see it.

**Deployment.** Every place that starts the process:

- Helm: add it to the right group in `charts/agentarea/config.yaml` (never edit
  `templates/configs/*.env.tpl` by hand), then `python scripts/generate_env_tpls.py`
  and helm-docs. Secrets go under `secrets:` and come from a Secret.
- Compose: `docker-compose.yaml`, `docker-compose.dev.yaml`, and
  `docker-compose.ci.yaml` if it overrides that service. Required secrets use
  `${NAME:?NAME is required; run scripts/gen-dev-secrets.sh}`, and go in
  `MANAGED_SECRET_KEYS` in `scripts/lib/secrets.sh`.
- `.env.example` if an operator is expected to set it.
- `.github/workflows/*`: the job-level `env:` is ours (`AGENTAREA_*`);
  `services.postgres.env` is the image's contract and keeps `POSTGRES_*`.

**Docs.**

- Add a row to `docs/self-host/configuration.md`.
- Renamed or removed: add a row to `docs/self-host/env-migration.md`. A rename
  goes under "Renamed", old to new. A removal goes under "Removed", with the
  reason.

**Outside this repo.** Production sets env in `agentarea/k8s-apps`
(`envs/production/*/applications/agentarea/values.yaml` and the wrapper charts),
the enterprise overlay in `agentarea/agentarea-enterprise`, and the sandbox VM in
`agentarea/infrastructure` (Ansible). A rename needs a companion PR in each one
that sets the name. The chart reaches prod through a pinned version in k8s-apps,
not with the image, so a new *required* variable crash-loops prod once the image
lands, unless k8s-apps already sets it.

## 5. Prove it

```sh
python scripts/check_env_naming.py   # needs PyYAML
```

The guard checks three things:

1. What the code reads follows the scheme.
2. No retired name (the migration table's old column) is still set by a chart,
   compose file, `.env.example` or workflow.
3. Every name `charts/agentarea/config.yaml` hands our processes is read by
   something.

It runs as the `env-naming` CI job, under `ci-required`. After any conflict in
`ci.yml`, check the job is still there (`git grep check_env_naming .github`): it
was lost to a rebase once, and CI stayed green while checking nothing.

The guard also cannot see a variable an SDK reads implicitly. The Go S3 clients
once used `awsconfig.LoadDefaultConfig`, which picks up `AWS_ACCESS_KEY_ID` on
its own. When the chart moved storage to `AGENTAREA_S3_*`, nothing failed until
production lost object-store access. Before renaming a name an SDK might read
by itself, grep for the implicit readers: `LoadDefaultConfig`, `boto3.client`
with no explicit keys, `os.environ` passed whole to a library, and pass the
values explicitly instead.

The guard cannot see test stubs or attribute access. Run `uv run pyright` for
the attribute side and `make test` for the stubs. If the chart changed, render
it (`helm template`) and check that each new name lands on the containers that
read it.
