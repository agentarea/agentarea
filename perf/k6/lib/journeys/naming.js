// Every resource a write journey creates carries a name the janitor
// (janitor.js) can find and delete later — including a leftover from a run
// that crashed before it could clean up after itself.
//
// `isOurs` is a strict regex, not a prefix check, on purpose: `GET
// /mcp-servers/` (and any other list endpoint that mixes tenant rows with
// platform/catalog projections — the API gives no clean way to tell them
// apart by name alone) returns catalog items too, and a future catalog
// entry that merely starts with "k6-" (a Grafana k6 MCP server, say) must
// never match. The full shape this suite ever produces is
// `k6-<testid>-<kind>-<vu>-<iter>-<13-digit-ms-timestamp>` — every segment
// after the testid is fully under this suite's control, so the regex anchors
// on that suffix instead of just the prefix.
import { TESTID } from "../config.js";

export const RESOURCE_PREFIX = "k6-";

// The complete, closed set of `kind` values resourceName() is ever called
// with — keep this in sync with every resourceName("...") call site (there's
// a self-test in scenarios/journeys/smoke.js that will fail loudly if it
// drifts: it calls resourceName with each of these and asserts isOurs()).
export const KINDS = [
  "agent",
  "skill",
  "mcp-spec",
  "mcp-instance",
  "openapi",
  "trigger",
  "trigger-agent",
  "task-agent",
];

const OWNED_NAME_PATTERN = new RegExp(`^${RESOURCE_PREFIX}.+-(${KINDS.join("|")})-\\d+-\\d+-\\d{13}$`);

export function resourceName(kind) {
  if (!KINDS.includes(kind)) {
    // Fails the run immediately rather than silently creating a resource the
    // janitor's regex can never find again.
    throw new Error(`resourceName: unknown kind "${kind}" — add it to KINDS in lib/journeys/naming.js`);
  }
  // __VU/__ITER keep two VUs creating the same kind in the same iteration
  // window from colliding on a unique-per-workspace name field.
  return `${RESOURCE_PREFIX}${TESTID}-${kind}-${__VU}-${__ITER}-${Date.now()}`;
}

export function isOurs(name) {
  return typeof name === "string" && OWNED_NAME_PATTERN.test(name);
}
