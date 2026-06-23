"use server";

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
import { getAuthContext } from "@/lib/getAuthContext";

export interface AuditChange {
  field: string;
  before?: unknown;
  after?: unknown;
}

export interface AuditEvent {
  id: string;
  action: string;
  actor_id: string;
  actor_type: string;
  resource_type: string;
  resource_id?: string | null;
  source_ip?: string | null;
  created_at: string;
  changes?: AuditChange[];
  actor?: AuditActorDisplay;
  resource?: AuditResourceDisplay;
}

export interface AuditLogResponse {
  events: AuditEvent[];
  next_cursor: string | null;
}

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

export async function fetchAuditLogs(params?: {
  action?: string;
  resource_type?: string;
  actor_id?: string;
  resource_id?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}): Promise<{ data: AuditLogResponse | null; error: string | null }> {
  const { data, error } = await listAuditLogs(params);

  if (error) {
    return { data: null, error: "Failed to fetch audit logs" };
  }

  const raw = data as unknown as AuditLogResponse;
  const events = await enrichAuditEvents(raw.events ?? []);

  return { data: { ...raw, events }, error: null };
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
    auth.workspaceId
      ? listWorkspaceMembers(auth.workspaceId)
          .then((result) => {
            for (const member of asArray<ResourceRecord>(result.data)) {
              if (typeof member.user_id === "string") {
                members.set(member.user_id, member);
              }
            }
          })
          .catch(() => undefined)
      : Promise.resolve(),
    events.some((event) => event.actor_type === "agent")
      ? listAgents()
          .then((result) => {
            for (const agent of asArray<ResourceRecord>(result.data)) {
              const id = getString(agent.id);
              if (id) agents.set(id, agent);
            }
          })
          .catch(() => undefined)
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
        .catch(() => undefined)
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
    (id) => `/mcp-servers/${id}`
  );
  queue(
    ["mcp_server"],
    () => fetchData(listMCPServers({ page_size: 100 })),
    "MCP server",
    () => "/mcp-servers"
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
    (id) => `/admin/provider-configs/edit/${id}`
  );
  queue(
    ["api_key"],
    () => fetchData(listAPIKeys()),
    "API key",
    () => "/admin/api-keys"
  );

  await Promise.all(jobs);
  return index;
}

async function fetchData<T>(promise: Promise<{ data?: T; error?: unknown }>) {
  const { data, error } = await promise;
  if (error) return [];
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
      href: "/admin/api-keys",
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

  return {
    label: fallbackResourceLabel(event.resource_type, event.resource_id),
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
    Array.isArray((value as any).items)
  ) {
    return (value as any).items as T[];
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
    if (type === "mcp_server" || type === "mcp_instance") return "/mcp-servers";
    if (type === "governance_policy" || type === "policy") return "/policies";
    if (type === "api_key") return "/admin/api-keys";
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
      return `/mcp-servers/${id}`;
    case "mcp_server":
      return "/mcp-servers";
    case "governance_policy":
    case "policy":
      return "/policies";
    case "project":
      return `/projects/${id}`;
    case "openapi_connection":
      return "/connections?tab=openapi";
    case "provider_config":
      return `/admin/provider-configs/edit/${id}`;
    case "api_key":
      return "/admin/api-keys";
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
