// Single source of truth for what gets hit and how it's grouped into "page
// loads" — both smoke (runs every page once) and baseline/stress (pick one
// page per iteration) read this same list, so the endpoint set never drifts
// between scenarios.
//
// `name` tags are route templates, not full URLs — a scan across identical
// requests. The five catalog/browse variants share one route but exist to
// answer different questions (does sort cost anything, does a free-text
// filter, does paging past offset 4800), so each gets its own name suffix
// instead of collapsing into one "catalog/browse" bucket that would hide the
// difference. Kept free of `{`, `}`, `,`, `:` — k6's threshold tag-filter
// parser (lib/thresholds.js wraps every name in `{name:...}`) treats those as
// syntax, not text, and silently mangles the expression if they show up in a
// tag value.
//
// To add an endpoint: add it to `NAMES`, then either extend an existing page
// or push a new `{ name, run }` onto `pages` (wrap the request in
// `timedPage(...)` so it gets a page_load_duration sample too).
import { group } from "k6";
import { BASE_URL, WORKSPACE } from "./config.js";
import { get, batchGet } from "./http.js";
import { pageLoadDuration, pageVisits } from "./metrics.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

export const NAMES = {
  HEALTH: "GET /health",
  WORKSPACES: "GET /v1/workspaces",
  MCP_SERVERS: "GET /v1/workspaces/WS/mcp-servers/",
  MCP_SERVER_INSTANCES: "GET /v1/workspaces/WS/mcp-server-instances/",
  OPENAPI_CONNECTIONS: "GET /v1/workspaces/WS/openapi-connections/",
  AGENTS: "GET /v1/workspaces/WS/agents/",
  CATALOG_SKILLS: "GET /v1/workspaces/WS/registries/catalog/browse skills",
  CATALOG_SKILLS_SORT_NAME: "GET /v1/workspaces/WS/registries/catalog/browse skills sort_name",
  CATALOG_MCP_SERVERS: "GET /v1/workspaces/WS/registries/catalog/browse mcp_servers",
  CATALOG_SEARCH: "GET /v1/workspaces/WS/registries/catalog/browse skills search",
  CATALOG_DEEP_PAGE: "GET /v1/workspaces/WS/registries/catalog/browse skills deep_page",
  SKILLS: "GET /v1/workspaces/WS/skills",
  TRIGGERS: "GET /v1/workspaces/WS/triggers/",
  TASKS: "GET /v1/workspaces/WS/tasks/",
  INBOX: "GET /v1/workspaces/WS/inbox/",
};

function timedPage(pageName, fn) {
  const start = Date.now();
  group(`page: ${pageName}`, fn);
  pageLoadDuration.add(Date.now() - start, { page: pageName });
  pageVisits.add(1, { page: pageName });
}

function catalogPage(pageName, name, query) {
  return {
    name: pageName,
    run: () =>
      timedPage(pageName, () => {
        get(`${ws("/registries/catalog/browse")}?${query}`, name);
      }),
  };
}

export const pages = [
  {
    // Unauthenticated floor: network + gateway only, no app work.
    name: "health",
    run: () =>
      timedPage("health", () => {
        // health lives outside /v1 and needs no token.
        get(`${BASE_URL}/health`, NAMES.HEALTH);
      }),
  },
  {
    name: "workspaces",
    run: () =>
      timedPage("workspaces", () => {
        get(`${BASE_URL}/v1/workspaces`, NAMES.WORKSPACES);
      }),
  },
  {
    // Real page behavior (agentarea-webapp MCPServersContent.tsx): mcp-servers
    // is awaited first, then instances/openapi/agents fire in parallel.
    name: "connections",
    run: () =>
      timedPage("connections", () => {
        get(`${ws("/mcp-servers/")}?page_size=100`, NAMES.MCP_SERVERS);
        batchGet([
          { path: ws("/mcp-server-instances/"), name: NAMES.MCP_SERVER_INSTANCES },
          { path: ws("/openapi-connections/"), name: NAMES.OPENAPI_CONNECTIONS },
          { path: ws("/agents/"), name: NAMES.AGENTS },
        ]);
      }),
  },
  // Explore/catalog: the real page issues exactly one browseCatalog call per
  // view (agentarea-webapp explore/page.tsx), so each variant below is its
  // own single-request "page load" rather than a batch.
  catalogPage("explore_skills", NAMES.CATALOG_SKILLS, "registry_type=skills&limit=48&offset=0"),
  catalogPage(
    "explore_skills_sort_name",
    NAMES.CATALOG_SKILLS_SORT_NAME,
    "registry_type=skills&limit=48&offset=0&sort=name"
  ),
  catalogPage(
    "explore_mcp_servers",
    NAMES.CATALOG_MCP_SERVERS,
    "registry_type=mcp_servers&limit=48&offset=0"
  ),
  catalogPage(
    "explore_search_git",
    NAMES.CATALOG_SEARCH,
    "registry_type=skills&limit=48&offset=0&q=git"
  ),
  catalogPage(
    "explore_deep_page",
    NAMES.CATALOG_DEEP_PAGE,
    "registry_type=skills&limit=48&offset=4800"
  ),
  {
    name: "skills",
    run: () => timedPage("skills", () => get(ws("/skills"), NAMES.SKILLS)),
  },
  {
    name: "triggers",
    run: () => timedPage("triggers", () => get(ws("/triggers/"), NAMES.TRIGGERS)),
  },
  {
    name: "tasks",
    run: () => timedPage("tasks", () => get(ws("/tasks/"), NAMES.TASKS)),
  },
  {
    name: "inbox",
    run: () => timedPage("inbox", () => get(ws("/inbox/"), NAMES.INBOX)),
  },
];
