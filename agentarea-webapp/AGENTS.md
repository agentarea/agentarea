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
- **Tests**: only where there is logic to state as a rule — URL/string derivation, layout geometry, reducers, data shaping. Do not write tests that assert a component rendered or a label is on screen. Fixtures use our own domains (`agentarea.ai`), not third-party brands.
- **Shared components first**: before writing UI, look for the existing component in `src/components/` (and `src/components/ui/` for shadcn atoms). A visual pattern that appears twice lives in one component used twice — never a second local copy. Extract into `src/components/` in the same change that creates the second usage.
- **Status rendering**: task status on *any* surface (list, table cell, page header, inbox, filter, sheet, card) goes through `@/components/TaskStatus` — `<TaskStatus status={...} />`, `caption="auto" | "never"` for dense rows, `useTaskStatusLabel(status)` for prose. Every other entity status (agent, trigger, MCP, API key, payment, policy, invitation, sandbox) uses a `get<Entity>StatusPresentation()` from `@/lib/status` fed into `<StatusIndicator>`. New status values get a case in `@/lib/status`, not a call-site map. Details in `Design.md` §"Status / banners".

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

## COMMANDS

```bash
pnpm dev            # Development server :3000
pnpm build          # Production build
pnpm lint           # ESLint
pnpm type-check     # tsc --noEmit
pnpm format         # Prettier + import sort
pnpm generate:api   # Refresh openapi.json from backend + regenerate client
```
