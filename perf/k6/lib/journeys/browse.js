// Read-only page-load journeys. Every request pattern here was traced from
// the actual webapp source (agentarea-webapp/src/app/w/[workspace]/(main)/*),
// not guessed — sequential vs. parallel matters for what these numbers mean:
//
//   dashboard        1 call                              GET .../dashboard
//   agents           6-way parallel (AgentsContent.tsx)   agents/, model-instances/,
//                                                          mcp-server-instances/, mcp-servers/,
//                                                          openapi-connections/, tasks/
//   connections      mcp-servers/ awaited, THEN 3-way     (MCPServersContent.tsx)
//                    parallel: mcp-server-instances/, openapi-connections/, agents/
//   explore_*        1 call each, one browseCatalog per   (explore/page.tsx) — 5 variants:
//                    view (no batching in the real page)  default/sort/type/search/deep-page
//   skills           1 call                               GET .../skills
//   tasks            2-way parallel (TasksData.tsx)        tasks/, triggers/catalog
//   inbox            1 call                               GET .../inbox/
//   triggers         3-way parallel (TriggersContent.tsx)  triggers/, agents/, triggers/catalog
//
// Read-only: works against any workspace, not just perf-k6.
import { group } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, getPublic, batchGet } from "../http.js";
import { pageLoad, pageVisits } from "./metrics.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

function timedPage(pageName, fn) {
  const start = Date.now();
  group(`page: ${pageName}`, fn);
  pageLoad.add(Date.now() - start, { page: pageName, journey: "browse" });
  pageVisits.add(1, { page: pageName, journey: "browse" });
}

function catalogPage(pageName, query) {
  return {
    name: pageName,
    run: () =>
      timedPage(pageName, () => {
        get(`${ws("/registries/catalog/browse")}?${query}`, pageName, tag("browse", pageName, pageName));
      }),
  };
}

export const pages = [
  {
    // Unauthenticated floor: network + gateway only, no app work.
    name: "health",
    run: () =>
      timedPage("health", () => {
        getPublic(`${BASE_URL}/health`, "health", tag("browse", "health", "health"));
      }),
  },
  {
    name: "workspaces",
    run: () =>
      timedPage("workspaces", () => {
        get(`${BASE_URL}/v1/workspaces`, "workspaces", tag("browse", "workspaces", "workspaces"));
      }),
  },
  {
    name: "dashboard",
    run: () =>
      timedPage("dashboard", () => {
        get(ws("/dashboard"), "dashboard", tag("browse", "dashboard", "dashboard"));
      }),
  },
  {
    // AgentsContent.tsx: one Promise.all, no waterfall.
    name: "agents",
    run: () =>
      timedPage("agents", () => {
        batchGet([
          { path: ws("/agents/"), name: "agents", tags: tag("browse", "agents", "agents") },
          {
            path: ws("/model-instances/"),
            name: "model_instances",
            tags: tag("browse", "model_instances", "agents"),
          },
          {
            path: ws("/mcp-server-instances/"),
            name: "mcp_instances",
            tags: tag("browse", "mcp_instances", "agents"),
          },
          {
            path: `${ws("/mcp-servers/")}?page_size=100`,
            name: "mcp_servers",
            tags: tag("browse", "mcp_servers", "agents"),
          },
          {
            path: ws("/openapi-connections/"),
            name: "openapi_connections",
            tags: tag("browse", "openapi_connections", "agents"),
          },
          { path: ws("/tasks/"), name: "tasks", tags: tag("browse", "tasks", "agents") },
        ]);
      }),
  },
  {
    // MCPServersContent.tsx: mcp-servers/ is awaited first, then the other
    // three fire in parallel — a real waterfall, not an artifact of this suite.
    name: "connections",
    run: () =>
      timedPage("connections", () => {
        get(
          `${ws("/mcp-servers/")}?page_size=100`,
          "mcp_servers",
          tag("browse", "mcp_servers", "connections")
        );
        batchGet([
          {
            path: ws("/mcp-server-instances/"),
            name: "mcp_instances",
            tags: tag("browse", "mcp_instances", "connections"),
          },
          {
            path: ws("/openapi-connections/"),
            name: "openapi_connections",
            tags: tag("browse", "openapi_connections", "connections"),
          },
          { path: ws("/agents/"), name: "agents", tags: tag("browse", "agents", "connections") },
        ]);
      }),
  },
  catalogPage("explore_skills", "registry_type=skills&limit=48&offset=0"),
  catalogPage("explore_skills_sort_name", "registry_type=skills&limit=48&offset=0&sort=name"),
  catalogPage("explore_mcp_servers", "registry_type=mcp_servers&limit=48&offset=0"),
  catalogPage("explore_search_git", "registry_type=skills&limit=48&offset=0&q=git"),
  catalogPage("explore_deep_page", "registry_type=skills&limit=48&offset=4800"),
  {
    name: "skills",
    run: () =>
      timedPage("skills", () => get(ws("/skills"), "skills", tag("browse", "skills", "skills"))),
  },
  {
    // TasksData.tsx: tasks list + trigger catalog (for channel chips), parallel.
    name: "tasks",
    run: () =>
      timedPage("tasks", () => {
        batchGet([
          { path: `${ws("/tasks/")}?limit=50&offset=0`, name: "tasks", tags: tag("browse", "tasks", "tasks") },
          {
            path: ws("/triggers/catalog"),
            name: "trigger_catalog",
            tags: tag("browse", "trigger_catalog", "tasks"),
          },
        ]);
      }),
  },
  {
    name: "inbox",
    run: () =>
      timedPage("inbox", () => get(ws("/inbox/"), "inbox", tag("browse", "inbox", "inbox"))),
  },
  {
    // TriggersContent.tsx: triggers + owning agents (for the picker) + catalog.
    name: "triggers",
    run: () =>
      timedPage("triggers", () => {
        batchGet([
          { path: ws("/triggers/"), name: "triggers", tags: tag("browse", "triggers", "triggers") },
          { path: ws("/agents/"), name: "agents", tags: tag("browse", "agents", "triggers") },
          {
            path: ws("/triggers/catalog"),
            name: "trigger_catalog",
            tags: tag("browse", "trigger_catalog", "triggers"),
          },
        ]);
      }),
  },
];
