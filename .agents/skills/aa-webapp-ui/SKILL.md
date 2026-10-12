---
name: aa-webapp-ui
description: Use when writing or refactoring UI in agentarea-webapp/src — a page, a form, a detail screen, a dialog, or any component that loads data, holds state, or calls a server action. Decides where each piece of state lives (server component, form, URL, action, local) and which component boundary carries it, so a screen does not grow a wall of useState + useEffect.
---

# Writing AgentArea UI

Read `agentarea-webapp/AGENTS.md` (CONVENTIONS, ANTI-PATTERNS) and the
"Patterns & Conventions" part of `agentarea-webapp/Design.md` first. They own
the visual rules: shared components, list pages, status, icons, routing. This
skill owns the other half: **where data and state live**.

No state-management library is added for this. Next 16 server components,
React 19 (`useActionState`, `useTransition`, `useOptimistic`), `react-hook-form`
and `nuqs` cover every case below. Effector / Zustand / Redux / Jotai /
React Query / SWR are not used: our state is server data, forms and local UI,
none of which is a global client store, and a second data cache would have to
be kept in sync with the RSC one.

## Where does this state live?

Classify every value before writing `useState`.

| The value is… | It lives in | Not in |
|---|---|---|
| Data from the backend (entity, list, counts) | A **server component** that `await`s `@/lib/api` and passes plain props down | `useState` + `useEffect` + a load action |
| "Loading" of that data | `<Suspense fallback>` or the route's `loading.tsx` | a `loading` flag |
| Load failure / missing entity | `requireApiData` / `optionalApiData` / `notFoundOnApi404` (`@/lib/server-resource`), the route's `error.tsx`, `notFound()` | `loadError` / `notFound` flags |
| Fields the user edits | `react-hook-form` (`useForm` + `zodResolver` on the generated `z*`) | one `useState` per field |
| "Has unsaved changes", "is valid" | `formState.isDirty` / `formState.isValid` | a `hasChanges` flag kept in sync by hand |
| A mutation's pending / result / error | `useActionState` (form posts) or `useTransition` + the action's returned result | `saving` + `saved` + `actionError` flags |
| Fresh data after a mutation | `revalidatePath(await requestWorkspacePath(...))` or `refresh()` from `next/cache` inside the action; `router.refresh()` only from a client handler | refetching into local state, a `reloadKey` counter |
| Filter, tab, sort, page, selected item, open panel that should survive reload/share | the URL via `nuqs` (`useQueryState`) | `useState` |
| Anything computable from props/other state | a `const` in render (`useMemo` only if measured expensive) | `useState` + `useEffect` that copies it |
| A multi-step process (idle → running → done / failed) | **one** `useState` holding a discriminated union | several booleans |
| Truly local, ephemeral UI (dialog open, hover, accordion) | `useState` in the smallest component that uses it | the page component |
| Shared between distant client components on one screen | a narrow React context next to that screen (`TaskContext`, `NetworkProvider`) | prop drilling through 4 levels, or a new global store |

Rule of thumb: a component with more than ~5 `useState` is either loading data
on the client, re-implementing a form, storing derived values, or doing two
jobs. Find which and fix that — don't add a reducer to hold the same mess.

## Patterns

### Data: server page → data container → view

```
page.tsx            (server)  params, metadata, <Suspense fallback>
  └ XOverview.tsx   (server)  await the API in parallel, build a plain view model
      └ XOverviewView.tsx (client only if it needs interaction) render props
```

Reference: `triggers/[id]/page.tsx` → `components/TriggerOverview.tsx` →
`TriggerOverviewView`. Parallel loads: `connections/[id]/page.tsx`.

- **Never load data through a server action from `useEffect`.** Next dispatches
  client-invoked server actions **one at a time per page**
  (`node_modules/next/dist/docs/01-app/02-guides/server-actions.md`, "Sequential
  dispatch"), so a slow load action blocks every save/click queued behind it.
  Server actions are for mutations. Anti-reference: `skills/[id]/page.tsx`
  (`loadSkillDetailAction` in an effect, 30 `useState`).
- **No waterfalls.** Independent requests go through `Promise.all`; start a
  promise early and `await` it where it is needed. Sequential `await`s for
  unrelated data (as in `agents/shared/useAgentData.ts`) add their latencies.
- **Stream slow parts.** Wrap the slow, non-critical section in its own
  `<Suspense>` so the rest of the page renders first; don't block the page on
  the slowest call.
- **Serialize only what renders.** Pass the client component the fields it
  shows (a view model), not whole API responses.
- Data the client genuinely needs on demand (expand a row, open a file) may use
  a server action from an event handler — never from an effect that fires on
  mount, and never several in parallel (they queue).

### Forms

`react-hook-form` holding a typed object, `zodResolver` on the generated `z*`,
the server action re-validates the same schema and maps form → contract
through a pure adapter. Reference: `agents/shared/AgentForm.tsx` +
`agents/shared/agentContract.ts` + `agents/create/actions.ts`. A native
`<form action>` + `useActionState` is fine for a short form (reference:
`triggers/create/CreateTriggerForm.tsx`). `FormData` only for multipart.

Edit-in-place screens initialise the form from server props
(`defaultValues`), and after a successful save `reset(saved)` makes the new
values the clean baseline — no `editX` mirror of `x`.

### Mutations

```tsx
const [pending, startTransition] = useTransition();
const [error, setError] = useState<string | null>(null);

function onDelete() {
  startTransition(async () => {
    const result = await deleteThingAction(id); // revalidates on the server
    if (result.error) setError(result.error);
  });
}
```

The action returns `{ error }` or data shaped for the UI and revalidates the
path itself. `pending` comes from the transition — not a hand-set flag. Use
`useOptimistic` when the UI should show the result before the round-trip.

### Phases, not flags

```tsx
type Install =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; href: string }
  | { phase: "failed"; error: string };
const [install, setInstall] = useState<Install>({ phase: "idle" });
```

Impossible combinations (`loading && error`) can't be expressed. Reference:
`InstallState` in `bundles/components/CatalogGallery.tsx`.

### Effects

`useEffect` is for synchronising with something outside React (SSE,
`ResizeObserver`, a DOM API, a timer). It is not for:

- deriving state — compute it in render;
- reacting to a user action — do the work in the event handler;
- loading data — see "Data" above;
- resetting state when an id changes — give the component `key={id}`.

### Component boundaries

- One screen = one job per component. A detail page with view, edit, file
  browser and child management is four components, each with its own state.
- Keep `"use client"` at the leaves: the page and data containers stay server
  components; only the interactive island is client.
- Never define a component inside another component's body (it remounts every
  render and loses its state). Hoist it to module scope.
- Prefer composition over boolean props: explicit variants
  (`<CreateForm/>`, `<EditForm/>`) or children instead of `isEdit`,
  `isCompact`, `showX` flags that multiply branches.
- React 19: no `forwardRef` (ref is a prop); `use(Context)` over
  `useContext`.
- A file past ~400 lines is a split waiting to happen — `CatalogGallery.tsx`
  (2200+) is the example not to follow.

## Before you finish

- Every `useState` you added: which row of the table is it? If it's not
  "truly local UI" or "one phase union", move it.
- No server action is called from a mount effect.
- No `loading` / `error` / `hasChanges` / `reloadKey` flags for server data or
  forms.
- Verify by running the screen (`pnpm dev`), not with a jsdom test — see
  `agentarea-webapp/AGENTS.md` "TESTS (THIS DIR)".
