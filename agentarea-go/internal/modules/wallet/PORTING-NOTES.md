# wallet: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/wallet.md`.

## Fixed Python bugs

- Create stored the keys secret before the row, outside the row's transaction; a failed insert left the key
  (`libs/wallet/agentarea_wallet/application/wallet_service.py:73-95`). Secret and row now share one transaction.
- PUT replaced the whole credentials secret, so sending one key dropped the other (`wallet_service.py:183-187`);
  the web form sends only the keys typed. Keys sent are merged over the stored ones.
- DELETE swallowed a failed secret delete and dropped the wallet, orphaning the private key
  (`wallet_service.py:209-223`). A failed secret delete now fails the call, nothing is removed.
- `/payments` `total` ignored the filters and the page had no ORDER BY (`wallet_service.py:371`,
  `infrastructure/repository.py:117-135`). Total counts the filtered rows; newest first.
- `/fund` had no ValueError handler, so a stored wallet failing config validation answered 500
  (`apps/api/agentarea_api/api/v1/wallet.py:380-405`). It answers 400 like PUT.
- Timestamps were the API host's naive local time compared to UTC period windows
  (`infrastructure/repository.py:185-191`). Go writes naive UTC.
- A second completed payment under one key raised IntegrityError out of the activity. `Reserve` and
  `Complete` return `api.ErrAlreadySettled`, no aborted transaction.
- Security review fixes (2026-11-12):
  - A payment stored the agent id as the caller spelled it (`wallet_service.py:273-312` `record_payment`);
    any `uuid.Parse` form (uppercase, braces, `urn:uuid:`, no hyphens) found the wallet but escaped the
    lowercase-keyed spend sums. `Reserve` stores the wallet's canonical `agent_id`.
  - Budget check then write raced: `get_service_budget_remaining` read without a lock, the record went in
    without a recheck, sums counted only completed (`wallet_service.py:232-312`). Paying is now
    `Reserve` (one write transaction: `SELECT ... FOR UPDATE` on the wallet, sum completed + pending, insert a
    `pending` row or refuse with `*api.BudgetError`), then `Complete` / `Fail`. `api.Wallets.Remaining` and
    `Record` are gone; `Active.Remaining`, `/balance` `remaining` and `Exhausted` count pending holds
    (`spent` stays settled only). A retried `Reserve` under a pending key returns the same hold.
    Concurrency test on postgres:18: 24 parallel 0.25 reservations on a budget of 1 settle exactly 1.
  - The settled-key unique index was global while every lookup is per workspace (Alembic
    `uq_payment_records_settled_idempotency_key`): core goose `00002_payment_settled_key_per_workspace.sql`
    makes it `(workspace_id, idempotency_key) WHERE status = 'completed'`; `InsertPayment`'s ON CONFLICT
    follows. `tools/schemacheck` applies each set only up to its baseline, so it never compares this file.
  - With an external secrets backend (Infisical) the keys were written outside the row's transaction: create
    stored them before the insert, update before the row update, delete removed them before the row. Now the
    secret is written after the statement succeeds, a create whose transaction fails deletes the key it
    wrote, and delete removes the row then the secret, a failed secret delete failing the call and rolling
    the row back.
  - Update merged new keys over `{}` when the secret could not be read for any reason, dropping the stored
    key (`wallet_service.py:183-187` had no merge at all). Only `secrets.ErrNotFound` means none; other
    read errors fail the update.
  - Payment amounts had no lower exponent bound: `1E-2000000000` passed the range check and `Plain()` built
    a 2 GB string. Amounts are rounded to six places (`api.Quantize6`, ROUND_HALF_UP, shared with the
    budget validation) before anything expands them.

## Kept

- Execution-period `/balance` sums every execution of the agent (dossier oddity 7).
- A zero budget never pays (`remaining` 0); exact fit passes (the check is the caller's: `amount > remaining`).
- PUT null means unchanged; configs replace whole; dead settings (facilitator_url, signer_type,
  payment_method_types, stripe_profile_id) stay stored and returned.
- Auth order: reads check admin before resolving the agent; mutations resolve the agent (404) and validate
  the body (422) before the admin check (403).
- Payment history and keys are removed with the wallet (FK cascade); `payment_records` keeps `agent_id` as text.

## Blocked / open

- Slug paths: `service.AgentsFrom` resolves UUIDs through `agents/api.Lookup.AgentExists`; slugs resolve only
  if the lookup also has `AgentIDBySlug(ctx, ws, slug) (string, bool, error)`. Agents' `Lookup` lacks it
  (`agents/service.Service.Resolve` has the logic), so slug URLs (the web app uses them) 404 until agents adds it.
- Paying a 402 is connections' `payment.Session` (x402 EVM signer, MPP Tempo) over `api.Wallets`.
  Keys come back as `api.Credentials`, which never prints, logs or marshals.
- A payment the budget refuses leaves no `failed` row: `Reserve` refuses before inserting, and the
  refusal is only in the tool result. Python recorded a `failed` row for it (`record_payment_result`).
- A pending reservation holds budget for `api.ReservationHold` (40 min, the execute_tool StartToClose and
  Python `TOOL_EXECUTION_TIMEOUT`), measured from its `updated_at`; after that it belongs to a dead run and
  no longer counts, and a retried `Reserve` under its key makes a new hold, unless the hold is signed: a signed
  hold (`signed_headers`, core goose `00003_payment_signed_headers.sql`, written by `Sign` before the payment
  is sent) is returned at any age, so its payment is sent again and never signed twice. `Complete` of an expired hold
  still settles and counts (it was paid); the row stays `pending` otherwise (no sweeper).
- Agent deletion still orphans `wallet_creds_<agent>` (agents' delete path).
- `app/serve.go` mounts the routes; app passes `Wallets()` to connections (`UseWallets`) for the pay path.
- Suite `test/suite/wallet` compiles (`go vet -tags suite`) but was not run against a stack.
