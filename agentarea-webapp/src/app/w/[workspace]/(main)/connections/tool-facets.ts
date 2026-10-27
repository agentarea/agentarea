import type { ToolPolicy } from "./tool-policy";

// Untrusted safety hints supplied by the MCP server (per the MCP spec, clients
// must not rely on these for security — we surface them for labeling only).
export interface ToolAnnotations {
  title?: string;
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
}

export interface Tool {
  name: string;
  description: string;
  method?: string;
  path?: string;
  title?: string;
  annotations?: ToolAnnotations;
}

export interface ToolRow {
  id: string;
  name: string;
  title?: string;
  description: string;
  method?: string;
  path?: string;
  annotations?: ToolAnnotations;
}

/**
 * An agent that attaches this connection, as returned by
 * `GET /v1/mcp-server-instances/{id}/consumers`.
 */
export interface ToolsTableConsumer {
  agent_id: string;
  agent_name: string;
  agent_slug?: string | null;
  enabled_tools?: string[] | null;
  confirm_tools?: string[] | null;
}

/**
 * A principal equipped with one tool. "Equipped" is deliberate: the agent
 * carries the tool in its composition, the outer set of
 * Equipped ⊇ Authorized ⊇ Disclosed. Whether a call is authorized is decided by
 * the policy engine at dispatch time and is not part of this payload.
 */
export interface ToolPrincipal {
  agentId: string;
  name: string;
  slug?: string | null;
  needsConfirm: boolean;
  viaAllTools: boolean;
}

export type PrincipalLookup = (toolName: string) => ToolPrincipal[];

export type ToolFacet =
  | "all"
  | "equipped"
  | "unequipped"
  | "destructive"
  | "readOnly"
  | "denied"
  | "approval";

/** A tool's workspace policy; `null` where the list has none to show. */
export type ToolPolicyLookup = ((toolName: string) => ToolPolicy) | null;

export interface ToolGroup {
  key: string;
  label: string;
  rows: ToolRow[];
  open: boolean;
}

// Above this many tools a flat list stops being navigable and grouping kicks in.
export const GROUP_THRESHOLD = 24;
// Groups auto-opened at most, so a wide server never paints as one long scroll.
export const MAX_AUTO_OPEN_GROUPS = 3;

export const OTHER_GROUP_KEY = "__other__";

/**
 * Reverse index: tool name → agents equipped with it. Agents whose
 * `enabled_tools` is null are equipped with everything, so they are kept
 * apart instead of being fanned out across every tool name. `null` when there
 * is no consumer data to answer from.
 */
export function buildPrincipalLookup(
  consumers: ToolsTableConsumer[] | null | undefined
): PrincipalLookup | null {
  if (!consumers) return null;
  const byTool = new Map<string, ToolPrincipal[]>();
  const wildcard: {
    agentId: string;
    name: string;
    slug?: string | null;
    confirm: Set<string>;
  }[] = [];

  for (const consumer of consumers) {
    const confirm = new Set(consumer.confirm_tools ?? []);
    if (consumer.enabled_tools == null) {
      wildcard.push({
        agentId: consumer.agent_id,
        name: consumer.agent_name,
        slug: consumer.agent_slug,
        confirm,
      });
      continue;
    }
    for (const toolName of consumer.enabled_tools) {
      const principal: ToolPrincipal = {
        agentId: consumer.agent_id,
        name: consumer.agent_name,
        slug: consumer.agent_slug,
        needsConfirm: confirm.has(toolName),
        viaAllTools: false,
      };
      const list = byTool.get(toolName);
      if (list) list.push(principal);
      else byTool.set(toolName, [principal]);
    }
  }

  return (toolName: string) => [
    ...wildcard.map((w) => ({
      agentId: w.agentId,
      name: w.name,
      slug: w.slug,
      needsConfirm: w.confirm.has(toolName),
      viaAllTools: true,
    })),
    ...(byTool.get(toolName) ?? []),
  ];
}

function matchesFacet(
  tool: Tool,
  facet: ToolFacet,
  principalsFor: PrincipalLookup | null,
  policyOf: ToolPolicyLookup
): boolean {
  switch (facet) {
    case "equipped":
      return principalsFor ? principalsFor(tool.name).length > 0 : true;
    case "unequipped":
      return principalsFor ? principalsFor(tool.name).length === 0 : true;
    case "destructive":
      return tool.annotations?.destructiveHint === true;
    case "readOnly":
      return tool.annotations?.readOnlyHint === true;
    case "denied":
      return policyOf?.(tool.name) === "deny";
    case "approval":
      return policyOf?.(tool.name) === "approval";
    default:
      return true;
  }
}

export function filterTools(
  tools: Tool[],
  {
    query,
    facet,
    principalsFor,
    policyOf = null,
  }: {
    query: string;
    facet: ToolFacet;
    principalsFor: PrincipalLookup | null;
    policyOf?: ToolPolicyLookup;
  }
): Tool[] {
  const needle = query.trim().toLowerCase();
  return tools.filter((tool) => {
    if (needle) {
      const haystack = `${tool.name} ${tool.title ?? ""} ${tool.description ?? ""}`;
      if (!haystack.toLowerCase().includes(needle)) return false;
    }
    return matchesFacet(tool, facet, principalsFor, policyOf);
  });
}

export function countToolFacets(
  tools: Tool[],
  principalsFor: PrincipalLookup | null,
  policyOf: ToolPolicyLookup = null
): Record<ToolFacet, number> {
  let equipped = 0;
  let destructive = 0;
  let readOnly = 0;
  let denied = 0;
  let approval = 0;
  for (const tool of tools) {
    if (principalsFor && principalsFor(tool.name).length > 0) equipped++;
    if (tool.annotations?.destructiveHint) destructive++;
    if (tool.annotations?.readOnlyHint) readOnly++;
    const policy = policyOf?.(tool.name);
    if (policy === "deny") denied++;
    if (policy === "approval") approval++;
  }
  return {
    all: tools.length,
    equipped,
    unequipped: tools.length - equipped,
    destructive,
    readOnly,
    denied,
    approval,
  };
}

/**
 * Tools some agent holds by name. A single `all tools` agent equips every
 * tool, so counting it would stamp the same number on every group.
 */
export function countExplicitGrants(
  rows: ToolRow[],
  principalsFor: PrincipalLookup | null
): number {
  if (!principalsFor) return 0;
  return rows.filter((row) =>
    principalsFor(row.name).some((principal) => !principal.viaAllTools)
  ).length;
}

// Rows lead with the tool's name, so that is what they are ordered by.
const byName = (a: ToolRow, b: ToolRow) =>
  a.name.toLowerCase().localeCompare(b.name.toLowerCase());

export function toToolRows(tools: Tool[]): ToolRow[] {
  return tools
    .map((tool) => ({
      id: tool.name,
      name: tool.name,
      title: tool.title,
      description: tool.description,
      annotations: tool.annotations,
    }))
    .sort(byName);
}

// Verbs that big MCP servers put in front of the object they act on. Stripping
// them turns `create_issue` / `list_issues` / `get_issue` into one "issue"
// bucket instead of three verb buckets nobody navigates by.
// prettier-ignore
const TOOL_VERBS: Record<string, true> = {
  add: true, assign: true, cancel: true, close: true, copy: true, create: true,
  delete: true, describe: true, download: true, execute: true, fetch: true,
  find: true, get: true, list: true, merge: true, move: true, open: true,
  patch: true, post: true, put: true, query: true, read: true, remove: true,
  rename: true, run: true, search: true, send: true, set: true, start: true,
  stop: true, update: true, upload: true, write: true,
};

/**
 * Group key for an MCP tool name. Namespaced servers (`github__create_issue`,
 * `jira.search`) carry the namespace up front; flat servers name tools
 * verb-first, so the verb is dropped and the object carries the group.
 * Returns an empty string when the name yields no usable key.
 */
function nameGroup(name: string): string {
  const namespaced = name.match(/^([A-Za-z0-9]+)(?:__|\.|:|\/)/);
  if (namespaced) return namespaced[1].toLowerCase();

  const tokens = name.split(/[_\-\s]+/).filter(Boolean);
  if (!tokens.length) return "";
  const head = tokens[0].toLowerCase();
  const object = TOOL_VERBS[head] && tokens.length > 1 ? tokens[1] : head;
  const normalized = object.toLowerCase();
  // Singularize so `list_issues` and `get_issue` land in the same bucket.
  return normalized.endsWith("s") && !normalized.endsWith("ss")
    ? normalized.slice(0, -1)
    : normalized;
}

/**
 * Name groups for a wide MCP server; empty when the list is short enough to
 * read flat or a search has already narrowed it.
 */
export function groupToolsByName(
  rows: ToolRow[],
  {
    principalsFor,
    searching,
  }: { principalsFor: PrincipalLookup | null; searching: boolean }
): ToolGroup[] {
  if (searching || rows.length <= GROUP_THRESHOLD) return [];

  const buckets = new Map<string, ToolRow[]>();
  for (const row of rows) {
    const key = nameGroup(row.name) || OTHER_GROUP_KEY;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(row);
    else buckets.set(key, [row]);
  }

  // A bucket of one is not a group — it is noise with a header on top.
  const singles: ToolRow[] = [];
  const groups: ToolGroup[] = [];
  for (const [key, bucketRows] of buckets) {
    if (key === OTHER_GROUP_KEY || bucketRows.length < 2)
      singles.push(...bucketRows);
    else groups.push({ key, label: key, rows: bucketRows, open: false });
  }
  groups.sort(
    (a, b) => b.rows.length - a.rows.length || a.key.localeCompare(b.key)
  );
  if (singles.length) {
    singles.sort((a, b) => a.name.localeCompare(b.name));
    groups.push({
      key: OTHER_GROUP_KEY,
      label: OTHER_GROUP_KEY,
      rows: singles,
      open: false,
    });
  }

  // Open the groups holding explicitly granted tools; otherwise the first
  // one, so the section never paints as a wall of closed accordions.
  const ranked = groups
    .map((group) => ({
      group,
      grants: countExplicitGrants(group.rows, principalsFor),
    }))
    .filter((entry) => entry.grants > 0)
    .sort((a, b) => b.grants - a.grants)
    .slice(0, MAX_AUTO_OPEN_GROUPS);
  if (ranked.length) for (const entry of ranked) entry.group.open = true;
  else if (groups.length) groups[0].open = true;

  return groups;
}

const words = (text: string) =>
  text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2") // camelCase
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);

/**
 * Whether a tool's human title says more than its name. A title that only
 * spells the name out word for word (`delete_repo` → "Delete repository",
 * `search_issues` → "Search issues") repeats it; one with words of its own
 * ("Merge pull request", "Who am I") is worth showing.
 */
export function titleAddsToName(name: string, title?: string | null): boolean {
  if (!title?.trim()) return false;
  const nameWords = words(name);
  const titleWords = words(title);
  if (nameWords.length !== titleWords.length) return true;
  return titleWords.some((word, i) => {
    const stem = nameWords[i].replace(/s$/, "");
    return !word.startsWith(stem);
  });
}
