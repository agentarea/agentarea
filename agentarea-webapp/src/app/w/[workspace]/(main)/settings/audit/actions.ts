"use server";

import type {
  AuditEventResponse,
  AuditLogListResponse,
} from "@/api/client/types.gen";
import {
  getAllTasks,
  listAgents,
  listAPIKeys,
  listAuditLogs,
  listMCPServerInstances,
  listMCPServers,
  listOpenAPIConnections,
  listPolicies,
  listProjects,
  listProviderConfigs,
  listSkills,
  listTriggers,
  listWorkspaceMembers,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";

export type AuditChange = NonNullable<AuditEventResponse["changes"]>[number];

export type AuditEvent = AuditEventResponse & {
  actor?: AuditActorDisplay;
  resource?: AuditResourceDisplay;
};

export type AuditLogResponse = Omit<AuditLogListResponse, "events"> & {
  events: AuditEvent[];
};

export interface AuditActorDisplay {
  label: string;
  description?: string | null;
  href?: string | null;
  is_current_user?: boolean;
  actor_type: string;
}

export interface AuditResourceDisplay {
  label: string;
  type_label: string;
  href?: string | null;
  found: boolean;
}

type ResourceRecord = {
  id?: unknown;
  name?: unknown;
  display_name?: unknown;
  title?: unknown;
  agent_name?: unknown;
  token_prefix?: unknown;
  email?: unknown;
  user_id?: unknown;
};

type ResourceEntry = {
  label: string;
  typeLabel: string;
  href: string | null;
};

export interface AuditLogFilters {
  action?: string;
  resource_type?: string;
  actor_id?: string;
  resource_id?: string;
  since?: string;
  until?: string;
}

export async function fetchAuditLogs(
  params?: AuditLogFilters & { cursor?: string; limit?: number }
): Promise<
  { data: AuditLogResponse; error: null } | { data: null; error: string }
> {
  const result = await listAuditLogs(params);

  if (result.error || !result.data) {
    console.error("Failed to fetch audit logs", result.status, result.error);
    return {
      data: null,
      error: apiErrorMessage(result, "Failed to fetch audit logs"),
    };
  }

  const raw = result.data;
  const events = await enrichAuditEvents(raw.events);

  return { data: { ...raw, events }, error: null };
}

/** Pages an export reads at most: 50 pages of 100, newest first. */
const EXPORT_PAGE_LIMIT = 50;
const EXPORT_PAGE_SIZE = 100;

/**
 * Every event matching ``filters``, for a CSV export, unenriched: the file
 * carries ids, which stay meaningful after the named thing is gone.
 * ``truncated`` says the cap was reached before the oldest match.
 */
export async function exportAuditLogs(
  filters: AuditLogFilters
): Promise<
  | { data: { events: AuditEventResponse[]; truncated: boolean }; error: null }
  | { data: null; error: string }
> {
  const events: AuditEventResponse[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < EXPORT_PAGE_LIMIT; page++) {
    const result = await listAuditLogs({
      ...filters,
      cursor,
      limit: EXPORT_PAGE_SIZE,
    });
    if (result.error || !result.data) {
      console.error("Failed to export audit logs", result.status, result.error);
      return {
        data: null,
        error: apiErrorMessage(result, "Failed to export audit logs"),
      };
    }
    events.push(...result.data.events);
    if (result.data.events.length < EXPORT_PAGE_SIZE) {
      return { data: { events, truncated: false }, error: null };
    }
    cursor = result.data.next_cursor ?? undefined;
  }
  return { data: { events, truncated: true }, error: null };
}

export interface AuditActorOption {
  value: string;
  label: string;
  kind: "user" | "agent";
}

/** People and agents of the workspace, for the actor filter. */
export async function listAuditActorOptions(): Promise<AuditActorOption[]> {
  const [members, agents] = await Promise.all([
    fetchData(listWorkspaceMembers()),
    fetchData(listAgents()),
  ]);
  const options: AuditActorOption[] = [];
  for (const member of asArray<ResourceRecord>(members)) {
    const id = getString(member.user_id);
    if (id) {
      options.push({
        value: id,
        label: getActorName(member) ?? id,
        kind: "user",
      });
    }
  }
  for (const agent of asArray<ResourceRecord>(agents)) {
    const id = getString(agent.id);
    if (id) {
      options.push({
        value: id,
        label: getResourceName(agent) ?? id,
        kind: "agent",
      });
    }
  }
  return options;
}

async function enrichAuditEvents(events: AuditEvent[]): Promise<AuditEvent[]> {
  if (events.length === 0) return events;

  const [actorIndex, resourceIndex] = await Promise.all([
    buildActorIndex(events),
    buildResourceIndex(events),
  ]);

  return events.map((event) => ({
    ...event,
    actor: resolveActor(event, actorIndex),
    resource: resolveResource(event, resourceIndex),
  }));
}

async function buildActorIndex(events: AuditEvent[]): Promise<{
  currentUserId: string | null;
  currentUserLabel: string | null;
  members: Map<string, ResourceRecord>;
  agents: Map<string, ResourceRecord>;
}> {
  const auth = await getAuthContext();
  const members = new Map<string, ResourceRecord>();
  const agents = new Map<string, ResourceRecord>();

  await Promise.all([
    fetchData(listWorkspaceMembers())
      .then((records) => {
        for (const member of asArray<ResourceRecord>(records)) {
          if (typeof member.user_id === "string") {
            members.set(member.user_id, member);
          }
        }
      })
      .catch((err) =>
        console.error("Failed to load audit actor labels", err)
      ),
    events.some((event) => event.actor_type === "agent")
      ? listAgents()
          .then((result) => {
            if (result.error) {
              console.error("Failed to load audit actor labels", result.error);
            }
            for (const agent of asArray<ResourceRecord>(result.data)) {
              const id = getString(agent.id);
              if (id) agents.set(id, agent);
            }
          })
          .catch((err) =>
            console.error("Failed to load audit actor labels", err)
          )
      : Promise.resolve(),
  ]);

  if (auth.userId && !members.has(auth.userId)) {
    members.set(auth.userId, {
      id: auth.userId,
      user_id: auth.userId,
      display_name: auth.name || auth.email || auth.username,
      email: auth.email,
    });
  }

  return {
    currentUserId: auth.userId,
    currentUserLabel: auth.name || auth.email || auth.username,
    members,
    agents,
  };
}

async function buildResourceIndex(
  events: AuditEvent[]
): Promise<Map<string, ResourceEntry>> {
  const resourceTypes = new Set(events.map((event) => event.resource_type));
  const index = new Map<string, ResourceEntry>();
  const jobs: Promise<void>[] = [];

  const addRecords = (
    type: string,
    typeLabel: string,
    hrefFor: (id: string) => string | null,
    records: unknown
  ) => {
    for (const record of asArray<ResourceRecord>(records)) {
      const id = getString(record.id);
      if (!id) continue;
      index.set(resourceKey(type, id), {
        label: getResourceName(record) ?? fallbackResourceLabel(type, id),
        typeLabel,
        href: hrefFor(id),
      });
    }
  };

  const queue = (
    types: string[],
    load: () => Promise<unknown>,
    typeLabel: string,
    hrefFor: (id: string) => string | null
  ) => {
    if (!types.some((type) => resourceTypes.has(type))) return;
    jobs.push(
      load()
        .then((records) => {
          for (const type of types)
            addRecords(type, typeLabel, hrefFor, records);
        })
        .catch((err) =>
          console.error("Failed to load audit resource labels", err)
        )
    );
  };

  queue(
    ["agent"],
    () => fetchData(listAgents()),
    "Agent",
    (id) => `/agents/${id}`
  );
  queue(
    ["task"],
    () => fetchData(getAllTasks()),
    "Task",
    (id) => `/tasks/${id}`
  );
  queue(
    ["trigger"],
    () => fetchData(listTriggers()),
    "Trigger",
    (id) => `/triggers/${id}`
  );
  queue(
    ["skill"],
    () => fetchData(listSkills()),
    "Skill",
    (id) => `/skills/${id}`
  );
  queue(
    ["mcp_instance"],
    () => fetchData(listMCPServerInstances()),
    "MCP instance",
    (id) => `/connections/${id}`
  );
  queue(
    ["mcp_server"],
    () => fetchData(listMCPServers({ page_size: 100 })),
    "MCP server",
    () => "/connections"
  );
  queue(
    ["governance_policy", "policy"],
    () => fetchData(listPolicies()),
    "Policy",
    () => "/policies"
  );
  queue(
    ["project"],
    () => fetchData(listProjects()),
    "Project",
    (id) => `/projects/${id}`
  );
  queue(
    ["openapi_connection"],
    () => fetchData(listOpenAPIConnections()),
    "OpenAPI connection",
    () => "/connections?tab=openapi"
  );
  queue(
    ["provider_config"],
    () => fetchData(listProviderConfigs()),
    "Provider config",
    (id) => `/models/edit/${id}`
  );
  queue(
    ["api_key"],
    () => fetchData(listAPIKeys()),
    "API key",
    () => "/settings/api-keys"
  );

  await Promise.all(jobs);
  return index;
}

async function fetchData(
  promise: Promise<{ data?: unknown; error?: unknown }>
) {
  const { data, error } = await promise;
  if (error) {
    console.error("Failed to load audit resource labels", error);
    return [];
  }
  return data;
}

function resolveActor(
  event: AuditEvent,
  index: Awaited<ReturnType<typeof buildActorIndex>>
): AuditActorDisplay {
  const actorType = event.actor_type || "user";
  const isCurrentUser =
    actorType === "user" && event.actor_id === index.currentUserId;

  if (isCurrentUser) {
    return {
      label: "Me",
      description: index.currentUserLabel,
      href: "/settings",
      is_current_user: true,
      actor_type: actorType,
    };
  }

  if (actorType === "user") {
    const member = index.members.get(event.actor_id);
    const label = member ? getActorName(member) : null;
    return {
      label: label ?? shortId(event.actor_id),
      description: member?.email ? String(member.email) : null,
      href: "/members",
      actor_type: actorType,
    };
  }

  if (actorType === "agent") {
    const agent = index.agents.get(event.actor_id);
    return {
      label: agent
        ? (getResourceName(agent) ?? shortId(event.actor_id))
        : `Agent ${shortId(event.actor_id)}`,
      href: `/agents/${event.actor_id}`,
      actor_type: actorType,
    };
  }

  if (actorType === "api_key") {
    return {
      label: `API key ${shortId(event.actor_id)}`,
      description: event.actor_id,
      href: "/settings/api-keys",
      actor_type: actorType,
    };
  }

  return {
    label: `${titleize(actorType)} ${shortId(event.actor_id)}`,
    description: event.actor_id,
    actor_type: actorType,
  };
}

function resolveResource(
  event: AuditEvent,
  index: Map<string, ResourceEntry>
): AuditResourceDisplay {
  const typeLabel = resourceTypeLabel(event.resource_type);

  if (!event.resource_id) {
    return {
      label: typeLabel,
      type_label: typeLabel,
      href: fallbackResourceHref(event.resource_type, null),
      found: false,
    };
  }

  const entry = index.get(resourceKey(event.resource_type, event.resource_id));
  if (entry) {
    return {
      label: entry.label,
      type_label: entry.typeLabel,
      href: entry.href,
      found: true,
    };
  }

  // A deleted secret, a revoked key or a removed member is no longer listed;
  // the name recorded with the event still says which one it was.
  const recordedName = getString(event.event_metadata?.resource_name);
  return {
    label:
      recordedName ??
      fallbackResourceLabel(event.resource_type, event.resource_id),
    type_label: typeLabel,
    href: fallbackResourceHref(event.resource_type, event.resource_id),
    found: false,
  };
}

function resourceKey(type: string, id: string) {
  return `${type}:${id}`;
}

function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (
    value &&
    typeof value === "object" &&
    Array.isArray((value as Record<string, unknown>).items)
  ) {
    return (value as Record<string, unknown>).items as T[];
  }
  return [];
}

function getString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function getActorName(record: ResourceRecord): string | null {
  return (
    getString(record.display_name) ||
    getString(record.name) ||
    getString(record.email) ||
    getString(record.user_id)
  );
}

function getResourceName(record: ResourceRecord): string | null {
  return (
    getString(record.name) ||
    getString(record.display_name) ||
    getString(record.title) ||
    getString(record.agent_name) ||
    getString(record.token_prefix) ||
    getString(record.email)
  );
}

function fallbackResourceLabel(type: string, id: string) {
  return `${resourceTypeLabel(type)} ${shortId(id)}`;
}

function fallbackResourceHref(type: string, id: string | null): string | null {
  if (!id) {
    if (type === "mcp_server" || type === "mcp_instance") return "/connections";
    if (type === "governance_policy" || type === "policy") return "/policies";
    if (type === "api_key") return "/settings/api-keys";
    if (type === "secret") return "/secrets";
    if (type === "member" || type === "invitation") return "/members";
    return null;
  }

  switch (type) {
    case "agent":
      return `/agents/${id}`;
    case "task":
      return `/tasks/${id}`;
    case "trigger":
      return `/triggers/${id}`;
    case "skill":
      return `/skills/${id}`;
    case "mcp_instance":
      return `/connections/${id}`;
    case "mcp_server":
      return "/connections";
    case "governance_policy":
    case "policy":
      return "/policies";
    case "project":
      return `/projects/${id}`;
    case "openapi_connection":
      return "/connections?tab=openapi";
    case "provider_config":
      return `/models/edit/${id}`;
    case "api_key":
      return "/settings/api-keys";
    case "secret":
      return "/secrets";
    case "member":
    case "invitation":
      return "/members";
    default:
      return null;
  }
}

function resourceTypeLabel(type: string) {
  const labels: Record<string, string> = {
    agent: "Agent",
    task: "Task",
    trigger: "Trigger",
    skill: "Skill",
    mcp_server: "MCP server",
    mcp_instance: "MCP instance",
    governance_policy: "Policy",
    policy: "Policy",
    project: "Project",
    openapi_connection: "OpenAPI connection",
    provider_config: "Provider config",
    api_key: "API key",
    secret: "Secret",  // pragma: allowlist secret
    member: "Member",
    invitation: "Invitation",
    access_grant: "Access",
    client: "Harness",
  };
  return labels[type] ?? titleize(type);
}

function titleize(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function shortId(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}
