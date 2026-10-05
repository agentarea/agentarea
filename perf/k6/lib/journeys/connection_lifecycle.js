// MCP instance lifecycle (create -> list -> delete) plus an OpenAPI
// connection lifecycle (create -> delete), both against fully public,
// no-credential endpoints.
//
// The MCP instance is created from a real catalog entry when one qualifies:
// browse registry_type=mcp_servers, and take an item whose `spec.env_schema`
// is empty (no credentials needed — confirmed field name/shape) and whose
// `spec.connection_type === "url"` with a `spec.url` set, using the catalog
// item id as `server_spec_id` — the API resolves built-in specs by catalog
// item id (ADR-003), the same id the webapp's connect links use.
// `installed_entity_id` is not usable: it can point at a spec row a
// migration de-materialized. Connecting copies the catalog spec into the
// workspace (copy-on-write); that copy belongs to this run and is deleted
// with the instance — the catalog item itself is never touched.
//
// Falls back to creating our own throwaway MCPServerSpec (remote_url set
// directly) when no such catalog entry is found, or the catalog call fails —
// that spec IS ours, so it gets cleaned up too. The remote URL there is
// overridable via MCP_TEST_REMOTE_URL; verify it still resolves once the
// perf-k6 workspace exists.
//
// MCPServerInstanceCreate docs: "For URL-type instances the service
// synchronously verifies the endpoint" — that verification is part of what
// the create call's latency measures here, by design. json_spec.type must be
// sent explicitly as "url" even when the linked spec already carries
// remote_url — the create endpoint's response-status logic reads
// data.json_spec.get("type", "docker") straight off the request body and
// defaults to "docker" (misleading 202) if it's omitted.
import { check, group } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, postJson, del } from "../http.js";
import { assertWriteAllowed } from "./guard.js";
import { resourceName, isOurs, SUITE_TAG } from "./naming.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

const MCP_REMOTE_URL = __ENV.MCP_TEST_REMOTE_URL || "https://mcp.deepwiki.com/sse";
const OPENAPI_SPEC_URL =
  __ENV.OPENAPI_TEST_SPEC_URL || "https://petstore3.swagger.io/api/v3/openapi.json";
const OPENAPI_BASE_URL = __ENV.OPENAPI_TEST_BASE_URL || "https://petstore3.swagger.io/api/v3";

// { serverSpecId, remoteUrl, ownsSpec } | null
function findCatalogNoCredSource() {
  const res = get(
    `${ws("/registries/catalog/browse")}?registry_type=mcp_servers&limit=48&offset=0`,
    "find_catalog_entry",
    tag("connection_lifecycle", "find_catalog_entry")
  );
  if (res.status !== 200) return null;
  const body = res.json();
  const items = (body && body.items) || [];
  const candidate = items.find((item) => {
    const spec = item.spec || {};
    const envSchema = spec.env_schema || [];
    return spec.connection_type === "url" && spec.url && envSchema.length === 0;
  });
  if (!candidate) return null;
  return { serverSpecId: candidate.id, remoteUrl: candidate.spec.url, ownsSpec: false };
}

// { serverSpecId, remoteUrl, ownsSpec: true } | null
function createOwnSpecSource() {
  const specName = resourceName("mcp-spec");
  const specRes = postJson(
    ws("/mcp-servers/"),
    {
      name: specName,
      description: "Disposable spec created by the k6 perf suite.",
      remote_url: MCP_REMOTE_URL,
      env_schema: [],
      // The marker janitor.js's ownedMcpSpec() requires before ever
      // deleting a spec (see naming.js's SUITE_TAG).
      tags: [SUITE_TAG],
    },
    "create_spec",
    tag("connection_lifecycle", "create_mcp_spec")
  );
  check(specRes, { "mcp spec create -> 200/201": (r) => r.status === 200 || r.status === 201 });
  if (specRes.status >= 300) return null;
  const spec = specRes.json();
  return { serverSpecId: spec.id, specName, remoteUrl: MCP_REMOTE_URL, ownsSpec: true };
}

function mcpInstanceLifecycle() {
  const source = findCatalogNoCredSource() || createOwnSpecSource();
  if (!source) return;

  const instanceName = resourceName("mcp-instance");
  const instanceRes = postJson(
    ws("/mcp-server-instances/"),
    {
      name: instanceName,
      server_spec_id: source.serverSpecId,
      json_spec: { type: "url", endpoint_url: source.remoteUrl },
    },
    "create_instance",
    tag("connection_lifecycle", "create_mcp_instance")
  );
  check(instanceRes, {
    // URL instances verify synchronously (201); container instances are
    // accepted and verify in the background (202).
    "mcp instance create -> 2xx": (r) => r.status >= 200 && r.status < 300,
  });

  const listRes = get(
    ws("/mcp-server-instances/"),
    "list",
    tag("connection_lifecycle", "list_mcp_instances")
  );
  check(listRes, { "mcp instance list -> 200": (r) => r.status === 200 });

  if (instanceRes.status < 300) {
    const instance = instanceRes.json();
    const deleteInstanceRes = del(
      ws(`/mcp-server-instances/${instance.id}`),
      "delete_instance",
      tag("connection_lifecycle", "delete_mcp_instance")
    );
    check(deleteInstanceRes, {
      "mcp instance delete -> 204/200": (r) => [200, 204].includes(r.status),
    });
    // A catalog connect materialized a workspace copy of the spec for this
    // instance alone; leaving it would grow the workspace every iteration.
    if (!source.ownsSpec && instance.server_spec_id && instance.server_spec_id !== source.serverSpecId) {
      const deleteCopyRes = del(
        ws(`/mcp-servers/${instance.server_spec_id}`),
        "delete_spec_copy",
        tag("connection_lifecycle", "delete_mcp_spec_copy")
      );
      check(deleteCopyRes, {
        "mcp spec copy delete -> 204/200": (r) => [200, 204].includes(r.status),
      });
    }
  }

  // Only delete the spec if this run created it — a catalog-derived spec is
  // shared platform state, not ours to remove. isOurs() re-checks the exact
  // name this call itself generated, the same rule the janitor applies —
  // belt-and-suspenders on top of ownsSpec already tracking provenance.
  if (source.ownsSpec && isOurs(source.specName)) {
    const deleteSpecRes = del(
      ws(`/mcp-servers/${source.serverSpecId}`),
      "delete_spec",
      tag("connection_lifecycle", "delete_mcp_spec")
    );
    check(deleteSpecRes, { "mcp spec delete -> 204/200": (r) => [200, 204].includes(r.status) });
  }
}

function openApiConnectionLifecycle() {
  const name = resourceName("openapi");
  const createRes = postJson(
    ws("/openapi-connections/"),
    {
      name,
      base_url: OPENAPI_BASE_URL,
      spec_url: OPENAPI_SPEC_URL,
      description: "Disposable connection created by the k6 perf suite.",
    },
    "create",
    tag("connection_lifecycle", "create_openapi")
  );
  check(createRes, { "openapi connection create -> 201": (r) => r.status === 201 });
  if (createRes.status >= 300) return;
  const conn = createRes.json();

  const deleteRes = del(
    ws(`/openapi-connections/${conn.id}`),
    "delete_openapi",
    tag("connection_lifecycle", "delete_openapi")
  );
  check(deleteRes, { "openapi connection delete -> 204/200": (r) => [200, 204].includes(r.status) });
}

export const connectionLifecycle = {
  name: "connection_lifecycle",
  run: () => {
    assertWriteAllowed("connection_lifecycle");
    group("journey: connection_lifecycle", () => {
      mcpInstanceLifecycle();
      openApiConnectionLifecycle();
    });
  },
};
