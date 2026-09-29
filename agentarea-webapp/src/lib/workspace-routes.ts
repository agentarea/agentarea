/**
 * The workspace a page belongs to lives in its URL: `/w/{slug}/agents/...`.
 * App code keeps writing unprefixed paths (`/agents/123`); the link, router
 * and redirect helpers add the prefix from the slug of the page they run on.
 */

export const WORKSPACE_PATH_PREFIX = "/w";

// Top-level segments under src/app/w/[workspace]/(main). Kept in step with the
// directory by workspace-routes.test.ts.
export const WORKSPACE_ROUTES = [
  "admin",
  "agents",
  "apps",
  "budgets",
  "bundles",
  "clients",
  "connections",
  "dashboard",
  "explore",
  "files",
  "inbox",
  "members",
  "models",
  "network",
  "policies",
  "projects",
  "secrets",
  "settings",
  "skills",
  "tasks",
  "triggers",
  "workplace",
] as const;

export const WORKSPACE_HOME = "/dashboard";

const ROUTE_SET: ReadonlySet<string> = new Set(WORKSPACE_ROUTES);

/**
 * Where `/` lands inside the personal workspace. An MCP OAuth callback that
 * could not resolve its connection redirects to `/?oauth=error&reason=...`;
 * that lands on the connections list with the result kept, so the failure is
 * shown instead of dropped on the way to the dashboard.
 */
export function rootLandingPath(query: URLSearchParams): string {
  if (query.get("oauth") !== "error") return WORKSPACE_HOME;
  const kept = new URLSearchParams({ oauth: "error" });
  const reason = query.get("reason");
  if (reason) kept.set("reason", reason);
  return `/connections?${kept}`;
}

function splitSuffix(path: string): [string, string] {
  const index = path.search(/[?#]/);
  return index === -1 ? [path, ""] : [path.slice(0, index), path.slice(index)];
}

/** True for an unprefixed in-app path such as `/agents/1?tab=x`. */
export function isWorkspaceRoute(path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//")) return false;
  const [pathname] = splitSuffix(path);
  const first = pathname.split("/")[1] ?? "";
  return ROUTE_SET.has(first);
}

/** `workspacePath("acme", "/agents/1")` → `/w/acme/agents/1`. */
export function workspacePath(slug: string, path: string): string {
  const base = `${WORKSPACE_PATH_PREFIX}/${encodeURIComponent(slug)}`;
  if (path === "/" || path === "") return base;
  return path.startsWith("/") ? `${base}${path}` : `${base}/${path}`;
}

/** Prefix `href` when it is a workspace route and a slug is known. */
export function prefixWorkspaceHref(href: string, slug: string | null): string {
  return slug && isWorkspaceRoute(href) ? workspacePath(slug, href) : href;
}

/** The slug of a `/w/{slug}/...` pathname, or null for any other path. */
export function workspaceSlugFromPath(pathname: string): string | null {
  const [path] = splitSuffix(pathname);
  const segments = path.split("/");
  if (segments[0] !== "" || `/${segments[1]}` !== WORKSPACE_PATH_PREFIX) {
    return null;
  }
  const raw = segments[2];
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return null;
  }
}

/** `/w/acme/agents/1` → `/agents/1`; `/w/acme` → `/`; other paths unchanged. */
export function stripWorkspacePrefix(pathname: string): string {
  if (workspaceSlugFromPath(pathname) === null) return pathname;
  const rest = pathname.split("/").slice(3).join("/");
  return `/${rest}`;
}

/**
 * Where switching workspace lands: the same top-level section, without the
 * ids below it, which belong to the workspace being left.
 */
export function workspaceSection(pathname: string): string {
  const first = stripWorkspacePrefix(pathname).split(/[/?#]/)[1] ?? "";
  return ROUTE_SET.has(first) ? `/${first}` : WORKSPACE_HOME;
}
