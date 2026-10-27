// The route of a workspace page with every slug and id replaced by `*`:
// `/w/acme/connections/create/86e0…` → `/w/*/connections/create/*`. This is
// all a page view may carry — never a workspace, an id or a query value.

// Set by the proxy only, overwriting anything the client sent: the page's
// path and the session's Kratos identity, for page-view analytics alone.
export const PAGE_VIEW_PATH_HEADER = "x-agentarea-page-path";
export const PAGE_VIEW_IDENTITY_HEADER = "x-agentarea-page-identity";

// Pages under src/app/w/[workspace], route groups dropped and each dynamic
// segment `*`. Pages that only redirect are left out. Kept in step with the
// directories by route-pattern.test.ts.
export const PAGE_ROUTES = [
  "/agents",
  "/agents/*",
  "/agents/*/new-task",
  "/agents/*/payments",
  "/agents/*/settings",
  "/agents/*/tasks",
  "/agents/*/wallet",
  "/agents/create",
  "/approve/*",
  "/apps",
  "/apps/*/*",
  "/budgets",
  "/bundles/import",
  "/clients",
  "/clients/*",
  "/connect/*",
  "/connect/catalog/*",
  "/connections",
  "/connections/*",
  "/connections/*/activity",
  "/connections/*/tools",
  "/connections/add",
  "/connections/add-openapi",
  "/connections/catalog/*",
  "/connections/create/*",
  "/connections/openapi/*",
  "/connections/openapi/*/tools",
  "/dashboard",
  "/events",
  "/events/*",
  "/events/streams",
  "/explore",
  "/files",
  "/inbox",
  "/members",
  "/models",
  "/models/create",
  "/models/create/*",
  "/models/edit/*",
  "/models/specs",
  "/network",
  "/policies",
  "/policies/*",
  "/policies/new",
  "/projects",
  "/projects/*",
  "/projects/*/files",
  "/projects/*/settings",
  "/projects/create",
  "/secrets",
  "/settings",
  "/settings/api-keys",
  "/settings/audit",
  "/settings/ory",
  "/settings/registries",
  "/skills",
  "/skills/*",
  "/skills/create",
  "/tasks",
  "/tasks/*",
  "/tasks/*/artifacts",
  "/tasks/*/events",
  "/tasks/*/files",
  "/triggers",
  "/triggers/*",
  "/triggers/*/edit",
  "/triggers/*/executions",
  "/triggers/*/metrics",
  "/triggers/create",
  "/workplace",
] as const;

const PATTERNS = PAGE_ROUTES.map((route) => route.split("/").slice(1));

function matches(pattern: string[], segments: string[]): boolean {
  return (
    pattern.length === segments.length &&
    pattern.every((part, index) =>
      part === "*" ? segments[index] !== "" : part === segments[index]
    )
  );
}

// As the router does: at the first segment where two matches differ, the
// static one wins (`/agents/create` over `/agents/*`).
function isMoreSpecific(pattern: string[], than: string[]): boolean {
  const index = pattern.findIndex((part, i) => part !== than[i]);
  return index !== -1 && than[index] === "*";
}

/** The page's route pattern, or null for anything that is not a workspace page. */
export function routePattern(pathname: string): string | null {
  const path = pathname.split(/[?#]/)[0].replace(/\/$/, "");
  const segments = path.split("/");
  if (segments[0] !== "" || segments[1] !== "w" || !segments[2]) return null;
  const rest = segments.slice(3);

  let best: string[] | null = null;
  for (const pattern of PATTERNS) {
    if (!matches(pattern, rest)) continue;
    if (!best || isMoreSpecific(pattern, best)) best = pattern;
  }
  return best ? `/w/*/${best.join("/")}` : null;
}
