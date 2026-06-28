# AI-driven E2E specs (Stagehand)

These `*.ai.spec.ts` tests drive the **real UI** with an LLM (via
[Stagehand](https://docs.stagehand.dev)) instead of hand-written selectors. You
describe a user journey ("configure an LLM provider", "create an agent") in
natural language and the model figures out where to click. This trades
determinism for coverage of broad, user-level happy paths — it is intentionally
less reliable than the selector-based `*.real.spec.ts` tests.

Authentication stays deterministic: a real Kratos user is created via the admin
API and its session cookie is injected into the browser (see
`helpers/stagehand.ts` → `withAuthedStagehand`). Only the in-page journey is
delegated to the model.

## What's covered

| Spec | FR | Journey |
|------|----|---------|
| `provider-config.ai.spec.ts` | FR-04 | Configure an LLM provider with an API key |
| `agent-create.ai.spec.ts` | FR-03 | Create an agent with a model |
| `openapi-tool.ai.spec.ts` | FR-08 | Register an OpenAPI spec and discover tools |
| `mcp-server.ai.spec.ts` | FR-07 | Add an MCP server |

## Prerequisites

1. A running real stack (API + Kratos + webapp). Same requirement as the
   `*.real.spec.ts` suite, e.g. `make up-dev` from the repo root and a webapp on
   `http://localhost:3000`.
2. An OpenRouter API key for the **driver** model (the LLM that decides where to
   click — unrelated to any provider configured *inside* the app under test).

## Environment

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `OPENROUTER_API_KEY` | yes | — | Key for the Stagehand driver model |
| `PLAYWRIGHT_REAL_STACK` | yes | — | Must be `1` (specs skip otherwise) |
| `STAGEHAND_MODEL` | no | `z-ai/glm-4.7` | OpenRouter model slug for the driver |
| `STAGEHAND_VERBOSE` | no | `1` | Stagehand log verbosity (`0`\|`1`\|`2`) |
| `HEADED` | no | — | Set to run the local browser headed (watch it click) |
| `PLAYWRIGHT_BASE_URL` | no | `http://localhost:3000` (via script) | App under test |
| `TEST_PROVIDER_API_KEY` | no | fake key | Key entered into the provider form (FR-04) |
| `TEST_OPENAPI_SPEC_URL` | no | swagger petstore | OpenAPI spec used by FR-08 |

> Note: the driver model must support tool/function calling. GLM 4.x on
> OpenRouter does. If you hit a model error, try `STAGEHAND_MODEL=z-ai/glm-4.6`
> or another tool-calling model. (There is currently no `glm-5.1` slug on
> OpenRouter — latest is `z-ai/glm-4.7`.)

## Two tiers

| Tier | Files | Project | Cost | Run |
|------|-------|---------|------|-----|
| 1 - deterministic | `*.real.spec.ts` (incl. `ui-smoke.real.spec.ts`) | `chromium-real-stack` | free (no LLM) | `pnpm test:e2e:smoke` / `pnpm test:e2e:real` |
| 2 - AI-driven | `*.ai.spec.ts` | `chromium-ai-stack` | LLM tokens | `pnpm test:e2e:ai` |

Run the cheap Tier 1 smoke (`pnpm test:e2e:smoke`) on every push - it visits
every top-level route and asserts each renders without crashing. Reach for the
AI tier only for form-filling journeys where a fixed selector script would be
brittle.

## Running

```bash
# against an already-running webapp on :3000
OPENROUTER_API_KEY=sk-or-... pnpm test:e2e:ai

# headed, single spec, verbose
OPENROUTER_API_KEY=sk-or-... HEADED=1 STAGEHAND_VERBOSE=2 \
  pnpm exec playwright test --project=chromium-ai-stack provider-config

# different driver model
OPENROUTER_API_KEY=sk-or-... STAGEHAND_MODEL=z-ai/glm-4.6 pnpm test:e2e:ai
```

## Reducing flakiness

- Prefer explicit step hints in `act()` over a single high-level goal.
- Keep auth/navigation deterministic (already done); only delegate the "soft"
  middle of the journey.
- Assert on concrete signals (URL, extracted booleans) rather than vibes.
- If a journey is consistently failing, the `act()` phrasing or the target route
  in the spec likely needs adjusting to match the current UI.
