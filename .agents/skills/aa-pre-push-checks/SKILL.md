---
name: aa-pre-push-checks
description: Use before pushing, force-pushing, opening or marking a PR ready, or claiming that checks pass on an agentarea branch, to select the smallest set of local checks that actually covers the outgoing diff instead of running the whole monorepo suite or trusting `make preflight` to mirror CI.
---

# AgentArea Pre-Push Checks

This is a polyglot monorepo: Python platform, Next.js webapp, two Go services, a
Node CLI, Helm charts. CI splits along those seams and skips everything your
diff does not touch. Match that. Running the whole suite for a one-package change
wastes minutes; running nothing and hoping wastes a CI round-trip.

`make preflight` exists and is useful, but **it is not a mirror of CI** despite
its header comment saying it mirrors `ci.yml`. The gaps are listed below. Never
report "preflight passed" as evidence that CI will pass.

## Find what the diff touches

CI's `changes` job classifies the diff with `dorny/paths-filter`
(`.github/workflows/ci.yml`). Every downstream job runs only if its filter
matched. Reproduce that classification first:

```sh
git status --short --branch
git diff --name-only "$(git merge-base HEAD origin/main)"...HEAD
```

Use the live PR base when it is not `main`. Map the changed paths through the
same filters CI uses:

| Changed path | Filter | Jobs that wake up |
|---|---|---|
| `agentarea-platform/**` | `platform` | `platform-lint`, `platform-test`, `platform-build`, `migrations-gate` |
| `agentarea-webapp/**` | `webapp` | `webapp-lint`, `webapp-build` |
| `agentarea-cli/**` | `cli` | `cli-test` |
| `agentarea-mcp-manager/**` | `mcp_manager` | `mcp-manager-lint-test` |
| `agentarea-event-service/**` | `events` | `events-lint-test` |
| `agentarea-operator/**` | `operator` | `docker-operator` |

`ci-required` is the aggregate gate; it treats a legitimately skipped job as a
pass, so an unmatched filter is not a hidden failure.

## Run the check CI will run

Run the command CI runs, not an approximation of it. Each of these is copied
from the job of the same name in `.github/workflows/ci.yml`.

**`platform-lint`** — all three, from `agentarea-platform/`. Format-check and
`pyright` are separate gates from `ruff check`; passing one proves nothing about
the others.

```sh
cd agentarea-platform
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

`pyright` is a ratchet: its bug-catching rules sit at `error` with a count of
zero, so a new real bug blocks the merge while known noise stays at `warning`.
A new `error` is your diff's, not pre-existing.

**`platform-test`** — CI runs `make test` verbatim, and the platform makefile
calls that target the single source of truth for the per-merge gate. It is
strictly wider than `pytest tests/unit tests/functional`: it also collects
`apps/api/tests`, `libs/common/tests`, `libs/tasks/tests`, seven `FLOW_TESTS`,
two `REDACTION_TESTS`, and a separate process for `SECRET_REDACTION_TESTS`.

```sh
cd agentarea-platform && make test
```

While iterating, run the owning test file directly — `uv run python -m pytest
<path> -m "not integration"`. Note the `uv run` prefix: `pytest` is not on the
`PATH` of the runtime container venv. Run `make test` once before pushing.

**`migrations-gate`** — triggered by any `agentarea-platform/**` change, not just
migration files. It asserts exactly one alembic head, applies migrations to a
fresh database, runs a downgrade/upgrade roundtrip on the last revision, and then
runs the Go `./internal/mcpgateway/...` tests against the migrated schema. If you
added a migration:

```sh
cd agentarea-platform/apps/api && uv run alembic upgrade head
```

Never run alembic from the repository root. Name new revisions with an ISO
timestamp, not the `aa`/`bb`/`cc` letter-pair scheme. Two heads is the usual
failure here, and it appears after a merge, not when you write the migration —
re-check it after merging main.

**`webapp-lint` / `webapp-build`** — the build doubles as the type check, and a
type error fails CI even though the standalone type-check step is warn-only.

```sh
cd agentarea-webapp
pnpm install --frozen-lockfile
pnpm run lint
pnpm run build
```

**`cli-test`**:

```sh
cd agentarea-cli && pnpm install --frozen-lockfile && pnpm run test
```

**`mcp-manager-lint-test` / `events-lint-test`** — both are Go, both run
`go test ./...` plus `golangci-lint`, but they are pinned differently:
`agentarea-mcp-manager` runs **golangci-lint v2.12.2**, while
`agentarea-event-service` runs **latest**. A locally installed golangci-lint is
one version for both, so a clean local run does not prove the pinned one is
clean. Trust the version match before trusting the result.

```sh
cd agentarea-mcp-manager && go test ./... && golangci-lint run ./...
cd agentarea-event-service && go test ./... && golangci-lint run ./...
```

Schema drift, Helm chart README, Helm lint, and env-template drift live in
separate workflows (`schema-check.yml`, `validate-helm.yml`) and are covered by
`make preflight`. If the diff touches API routes or `charts/`, run those.

## Where `make preflight` falls short

`scripts/preflight.sh` predates several CI jobs and its comments have drifted
from `ci.yml`. Treat these as uncovered:

- **`pyright` is skipped**, and the script's comment claims it is "declared in
  pyproject but NOT enforced by CI". That is wrong: `platform-lint` runs
  `uv run pyright` with no `continue-on-error`.
- **Python tests are a subset.** preflight runs `pytest tests/unit
  tests/functional`; CI runs `make test`.
- **`migrations-gate`, `cli-test`, `events-lint-test`, `version-check`, and
  `platform-build` are not run at all.** `agentarea-event-service` and
  `agentarea-cli` are invisible to preflight.

preflight does cover things CI splits into other workflows — schema drift,
helm-docs, helm lint, env templates — so it is worth running, just not worth
believing on its own.

Fix the script when you hit one of these rather than working around it here; a
skill that documents a lie is worse than a script that tells the truth.

## Handle failures

If a relevant check fails, fix it or explain the blocker. Do not push and hope CI
differs — it will not, and the round-trip costs more than the fix.

If a failure looks environment-specific, prove it: record the exact command, the
failing test, and the platform-specific mismatch, then confirm the checks that
are not platform-dependent still pass. Some triggers unit tests fail on `main`
independently of any branch; confirm against a clean checkout of the base before
attributing a failure to your diff.

## Push

```sh
git push
gh pr checks
```

Report pending checks as pending. Inspect a CI failure before attributing it to
the environment. For a history rewrite, fetch the current remote head, record its
OID, and push with `--force-with-lease=<branch>:<oid>` so a concurrent update
aborts the push; bare `--force` discards a teammate's work silently.
