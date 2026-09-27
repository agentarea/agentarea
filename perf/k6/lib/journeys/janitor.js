// Runs once, in setup(), before any journey: deletes every k6-prefixed
// leftover from a previous run (including one that crashed before its own
// inline cleanup ran). Order matters — triggers reference an agent_id and
// mcp-server-instances reference a server_spec_id, so children go first.
import { del, get } from "../http.js";
import { assertWriteAllowed, PERF_WORKSPACE } from "./guard.js";
import { isOurs, SUITE_TAG } from "./naming.js";
import { tag } from "./tags.js";
import { BASE_URL, WORKSPACE } from "../config.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

function sweep(listPath, deletePathFor, label, extraFilter) {
  const res = get(listPath, `janitor_list_${label}`, tag("janitor", `list_${label}`));
  if (res.status !== 200) {
    console.warn(`janitor: could not list ${label} (status ${res.status}), skipping sweep`);
    return 0;
  }
  const body = res.json();
  // skills and mcp-servers (specs) return PaginatedResponse ({items: [...]});
  // triggers/agents/mcp-server-instances/openapi-connections return a plain list.
  const items = Array.isArray(body) ? body : body.items || [];
  const ours = items.filter((item) => isOurs(item.name) && (!extraFilter || extraFilter(item)));
  for (const item of ours) {
    del(deletePathFor(item.id), `janitor_delete_${label}`, tag("janitor", `delete_${label}`));
  }
  return ours.length;
}

// `GET /mcp-servers/` mixes this workspace's own specs with platform/catalog
// projections — its own dependency comment says as much ("tenant specs are
// narrowed to what the graph says is readable; the catalog is not"), and the
// response model exposes no ownership field to filter on directly. SUITE_TAG
// (naming.js) is a tag only this suite ever writes; required here on top of
// (never instead of) the strict name regex isOurs() already applies.
export function ownedMcpSpec(item) {
  return Array.isArray(item.tags) && item.tags.includes(SUITE_TAG);
}

export function runJanitor() {
  assertWriteAllowed("janitor");
  console.log(`janitor: sweeping leftover k6- resources in workspace "${PERF_WORKSPACE}"`);

  const counts = {
    triggers: sweep(ws("/triggers/"), (id) => ws(`/triggers/${id}`), "triggers"),
    agents: sweep(ws("/agents/"), (id) => ws(`/agents/${id}`), "agents"),
    skills: sweep(ws("/skills"), (id) => ws(`/skills/${id}`), "skills"),
    mcp_instances: sweep(
      ws("/mcp-server-instances/"),
      (id) => ws(`/mcp-server-instances/${id}`),
      "mcp_instances"
    ),
    openapi_connections: sweep(
      ws("/openapi-connections/"),
      (id) => ws(`/openapi-connections/${id}`),
      "openapi_connections"
    ),
  };
  // MCP server specs last: instances (deleted above) reference them.
  // ownedMcpSpec guards against ever deleting a catalog/platform-shared item.
  counts.mcp_specs = sweep(
    `${ws("/mcp-servers/")}?page_size=100`,
    (id) => ws(`/mcp-servers/${id}`),
    "mcp_specs",
    ownedMcpSpec
  );

  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  console.log(`janitor: deleted ${total} leftover resource(s): ${JSON.stringify(counts)}`);
  return counts;
}
