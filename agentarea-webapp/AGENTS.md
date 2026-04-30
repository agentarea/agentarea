# AGENTS.md

**Generated:** 2026-03-02

Next.js 14+ app router frontend. Ory Kratos auth. SSE for real-time updates. npm workspaces.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add page | src/app/(main)/ |
| Add API route | src/app/api/ |
| Add component | src/components/ |
| Add hook | src/hooks/ |
| API client | src/lib/api-factory.ts, src/lib/browser-api.ts |
| Auth | src/lib/auth.ts, src/app/auth/ |
| Types | src/types/ |
| UI components | src/components/ui/ (shadcn) |
| Design tokens | Design.md |

## STRUCTURE

```
agentarea-webapp/
├── src/
│   ├── app/              # Next.js app router
│   │   ├── (main)/       # Authenticated pages
│   │   ├── auth/         # Auth pages (Kratos flows)
│   │   └── api/          # API routes (proxy to backend)
│   ├── components/       # React components
│   ├── hooks/            # Custom hooks (useSSE, useTaskEvents, useAuth)
│   ├── lib/              # API clients, utilities
│   └── types/            # TypeScript types
└── packages/             # npm workspaces
    ├── elements-react/   # Ory auth UI components
    └── nextjs/           # Ory Next.js integration
```

## CONVENTIONS

- **API calls**: Use `src/lib/api-factory.ts` (server) or `src/lib/browser-api.ts` (client)
- **Auth**: `useAuth()` hook for user state, `src/lib/auth.ts` for server auth
- **Real-time**: `useSSE()` or `useTaskEvents()` hooks for streaming
- **Styling**: Tailwind + shadcn/ui components
- **Types**: Shared types in `src/types/`, generated from OpenAPI

## KEY HOOKS

- `useAuth()` - User authentication state
- `useSSE(url)` - Server-sent events streaming
- `useTaskEvents(taskId)` - Task event subscription
- `useUser()` - Current user info
- `useModelInfo()` - LLM model metadata

## ROUTES (app/(main)/)

- `/agents` - Agent management
- `/agents/create` - Create agent wizard
- `/tasks` - Task history
- `/mcp-servers` - MCP server management
- `/settings` - Workspace settings

## ANTI-PATTERNS (THIS DIR)

- Never skip loading states during SSE
- Never store sensitive data in localStorage

## COMMANDS

```bash
npm run dev         # Development server :3000
npm run build       # Production build
npm run lint        # ESLint
npm run format      # Prettier + import sort
```
