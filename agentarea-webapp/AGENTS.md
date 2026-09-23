# AGENTS.md

**Generated:** 2026-03-02

Next.js 16 app router frontend. Ory Kratos auth. SSE for real-time updates. pnpm workspaces.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add page | src/app/(main)/ |
| Add API route | src/app/api/ |
| Add component | src/components/ |
| Add hook | src/hooks/ |
| API client (server-only) | src/lib/api.ts, src/lib/api-factory.ts |
| Generated API types/schemas | src/api/client/ (types.gen.ts, zod.gen.ts) |
| Auth | src/lib/auth.ts, src/app/auth/ |
| App types | src/types/ |
| UI components | src/components/ui/ (shadcn) |
| Design tokens | Design.md |

## STRUCTURE

```
agentarea-webapp/
├── src/
│   ├── app/              # Next.js app router
│   │   ├── (main)/       # Authenticated pages
│   │   ├── auth/         # Auth pages (Kratos flows)
│   │   └── api/          # Route handlers: file/stream proxy, SSE, OAuth
│   ├── components/       # React components
│   ├── hooks/            # Custom hooks (useSSE, useTaskEvents, useAuth)
│   ├── lib/              # API clients, utilities
│   └── types/            # TypeScript types
└── packages/             # npm workspaces
    ├── elements-react/   # Ory auth UI components
    └── nextjs/           # Ory Next.js integration
```

## CONVENTIONS

- **API access**: server-only via `src/lib/api.ts` (typed SDK over the generated `@hey-api` client). Client components reach the backend through **server actions** that call `@/lib/api` — never `fetch()` the backend from the browser.
- **API types & schemas**: generated from the OpenAPI spec into `@/api/client` (`types.gen.ts`, `zod.gen.ts`). Never hand-write a type or Zod schema that mirrors a backend contract. Regenerate with `pnpm generate:api` (refreshes `src/api/openapi.json` from the backend, then the client).
- **Forms**: react-hook-form holding a typed object + `zodResolver` on the generated `z*`; the server action validates the same `z*` and maps form→contract via a thin pure adapter (reference: `agents/create/actions.ts` + `agents/shared/agentContract.ts`). A native `<form action>` is fine for simple forms. Use `FormData` only for file/multipart uploads.
- **Auth**: `useAuth()` hook for user state, `src/lib/auth.ts` for server auth. The server SDK injects the token + `X-AgentArea-Workspace` automatically (`src/api/client-runtime.ts`) — never handle tokens manually.
- **Real-time**: `useSSE()` or `useTaskEvents()` hooks for streaming
- **Styling**: Tailwind + shadcn/ui components
- **List pages (grid+table)**: use `@/components/GridAndTableViews` — pass `data`, `columns`, `cardContent`, `itemLink`, `routeChange`, `searchParams`. Do NOT hand-roll a `<ul>`/`<div className="grid">` list or a bespoke card per page. Reference: `mcp-servers/ServerList.tsx`, `admin/providers/page.tsx`, `clients/page.tsx`, `projects/components/ProjectsContent.tsx`.
- **Entity icons**: single source of truth in `@/lib/entity-icons` (`ENTITY_ICONS[kind]` / `<EntityIcon kind="agent" />`). Kinds: agent→Bot, mcp→Server, skill→Sparkles, project→FolderTree, client→Plug, tool→Wrench, trigger→Zap. Do NOT inline `Bot`/`Server`/`Sparkles`/`Plug` from lucide for an entity — add the kind to the map instead.
- **Entity logos**: a *specific* connection is drawn by `<EntityMark identity={...} />` (`@/components/EntityMark`) over an identity from `@/lib/entity-identity` — registry logo → favicon of the host it points at → domain initials → the kind's glyph. Do NOT hand-roll an `<img onError>` fallback chain or a local initials mark; add the case to `entity-identity` instead.
- **Tests**: a frontend change gets **no test** by default. The rule and the two exceptions are in "TESTS (THIS DIR)" below.
- **Shared components first**: before writing UI, look for the existing component in `src/components/` (and `src/components/ui/` for shadcn atoms). A visual pattern that appears twice lives in one component used twice — never a second local copy. Extract into `src/components/` in the same change that creates the second usage.
- **Status rendering**: task status on *any* surface (list, table cell, page header, inbox, filter, sheet, card) goes through `@/components/TaskStatus` — `<TaskStatus status={...} />`, `caption="auto" | "never"` for dense rows, `useTaskStatusLabel(status)` for prose. Every other entity status (agent, trigger, MCP, API key, payment, policy, invitation, sandbox) uses a `get<Entity>StatusPresentation()` from `@/lib/status` fed into `<StatusIndicator>`. New status values get a case in `@/lib/status`, not a call-site map. Details in `Design.md` §"Status / banners".

## TESTS (THIS DIR)

Default for a frontend change is **no new test**. CI gates this app with
`pnpm lint` + `pnpm build` (`ci.yml` → `webapp-lint`, `webapp-build`) and with
type-check + generated-client drift (`frontend-integration.yml`). Neither
`vitest` nor Playwright runs in CI. A unit test added here is unenforced
weight: nothing runs it on a PR, and the next refactor pays for it.

Exactly two things earn a test:

1. **A pure module** — `.ts`, no React, no DOM: URL/string derivation, layout
   geometry, event-stream reducers, data shaping, parsers and sanitizers,
   session helpers. Colocated `*.test.ts`. This is why `lib/events/reducer.test.ts`
   and `network/utils/*Layout.test.ts` exist.
2. **A user-visible flow** — one Playwright spec under `tests/e2e/*.real.spec.ts`
   against the real stack, covering the flow end to end. Never one spec per
   control.

Everything else — a page, a component, a label, a prop, a variant, a wired
callback, a new section on an existing screen — gets nothing. Verify it by
running it: `pnpm dev` and drive the surface, or `pnpm test:e2e:smoke` against a
stand already up. Observed behaviour is the evidence, and it outranks any jsdom
assertion.

Never write, and delete on sight:

- `renderToStaticMarkup` + `expect(markup).toContain(...)` over an `aria-label`,
  a class name, or an `id` — that restates the component's own JSX.
- A test whose setup mocks the pieces the component is made of (`vi.mock` of
  `@/components/ui/select`, of every server action) and then asserts the markup
  those mocks produced.
- "renders without crashing", "the heading is on screen", component snapshots.
- A case per enum value or per prop when one case already covers the branch.

If UI logic feels worth testing, that is the signal it is not UI: lift it into a
pure module (`describeCron(expr)`, `toRequestBody(form)`) and test the function.

A React test is justified only for a stateful interaction with a real bug
history, driven through `@testing-library/user-event` in jsdom — reference:
`SecretSelect.test.tsx`, `triggers/create/CreateTriggerCredentials.test.tsx`.
Name the regression it catches in one line above the `describe`.

A test that fails this bar is deleted, not re-pinned to the new markup — the one
already on main included.

## KEY HOOKS

- `useAuth()` - User authentication state
- `useSSE(url)` - Server-sent events streaming
- `useTaskEvents(taskId)` - Task event subscription
- `useUser()` - Current user info
- `useModelInfo()` - LLM model metadata

## ROUTES (app/(main)/)

Representative — see `src/app/(main)/` for the full set (agents, tasks,
mcp-servers, policies, triggers, bundles, projects, connections, models,
secrets, inbox, workplace, admin, settings, ...).

- `/agents`, `/agents/create` - Agent management + create wizard
- `/tasks` - Task history
- `/mcp-servers` - MCP server management
- `/policies` - Access control / ReBAC policies
- `/triggers` - Automations (cron/webhook)
- `/settings` - Workspace settings

## ANTI-PATTERNS (THIS DIR)

- Never `fetch("/api/proxy/v1/...")` for JSON from the browser — use a server action on `@/lib/api`. `/api/proxy` is only for file download/streaming, SSE, and multipart upload.
- Never hand-write a Zod schema or TS type that duplicates a backend contract — import from `@/api/client`.
- Never `as any` a backend response — use the generated types/zod.
- Never skip loading states during SSE
- Never store sensitive data in localStorage
- Never hand-roll a status badge/dot (`bg-green-500`, a bare `<Badge>`, a local tone map) or re-derive a task's label/tone next to `<StatusIndicator>` — render `<TaskStatus>`; the divergence only shows up on the one page nobody re-checked.
- Never add a `*.test.tsx` that asserts rendered markup, and never answer "is this change proved?" with a jsdom test — a UI change is proved by running the surface or by an e2e spec. See "TESTS (THIS DIR)".

## COMMANDS

```bash
pnpm dev            # Development server :3000
pnpm build          # Production build
pnpm lint           # ESLint
pnpm type-check     # tsc --noEmit
pnpm format         # Prettier + import sort
pnpm generate:api   # Refresh openapi.json from backend + regenerate client
pnpm test           # vitest — pure modules only; NOT a CI gate
pnpm test:e2e:smoke # Playwright smoke against a stand already on :3000
```
