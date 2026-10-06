import type { AuditLogFilters as AuditQuery } from "./actions";

/** The resource types the audit trail records, in the order a reviewer scans them. */
export const AUDIT_RESOURCE_TYPES = [
  "task",
  "agent",
  "skill",
  "trigger",
  "mcp_server",
  "mcp_instance",
  "client",
  "governance_policy",
  "secret",
  "api_key",
  "member",
  "invitation",
  "access_grant",
] as const;

/** Every action the platform records, grouped by what it is about. */
export const AUDIT_ACTION_GROUPS = {
  toolCalls: [
    "tool.call.allowed",
    "tool.call.denied",
    "tool.call.approval_required",
    "approval.approved",
    "approval.denied",
  ],
  access: [
    "secret.create",
    "secret.update",
    "secret.rotate",
    "secret.delete",
    "api_key.create",
    "api_key.revoke",
    "member.invite",
    "member.invitation_revoke",
    "member.remove",
    "access.grant",
    "access.revoke",
    "governance_policy.create",
    "governance_policy.update",
    "governance_policy.set_enabled",
    "governance_policy.delete",
  ],
  config: [
    "agent.create",
    "agent.update",
    "agent.delete",
    "skill.create",
    "skill.update",
    "skill.delete",
    "trigger.create",
    "trigger.update",
    "trigger.delete",
    "trigger.signing_secret_rotate",
    "mcp_server.create",
    "mcp_server.update",
    "mcp_server.delete",
    "mcp_instance.create",
    "mcp_instance.update",
    "mcp_instance.delete",
    "task.create",
  ],
} as const;

const ALL_AUDIT_ACTIONS: readonly string[] =
  Object.values(AUDIT_ACTION_GROUPS).flat();

/** What an action is about: `secret.rotate` → `secret`, `tool.call.denied` → `tool.call`. */
export const actionSubject = (action: string) =>
  action.slice(0, action.lastIndexOf("."));

/** The action subject recorded for events about each resource type. */
const RESOURCE_ACTION_SUBJECT: Record<string, string> = {
  secret: "secret",
  api_key: "api_key",
  member: "member",
  invitation: "member",
  access_grant: "access",
  governance_policy: "governance_policy",
  agent: "agent",
  skill: "skill",
  trigger: "trigger",
  mcp_server: "mcp_server",
  mcp_instance: "mcp_instance",
  task: "task",
};

/**
 * The actions worth offering once a resource type is picked: only those about
 * it. With no resource, or one no action names, every action.
 */
export function actionsFor(resource?: string): readonly string[] {
  const subject = resource ? RESOURCE_ACTION_SUBJECT[resource] : undefined;
  return subject
    ? ALL_AUDIT_ACTIONS.filter((action) => actionSubject(action) === subject)
    : ALL_AUDIT_ACTIONS;
}

/** Relative periods; the same span in every timezone. */
export const AUDIT_PERIODS = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
  "90d": 90 * 24 * 60 * 60 * 1000,
} as const;

export type AuditPeriod = keyof typeof AUDIT_PERIODS;

/**
 * The audit filters as the page URL carries them. A custom range is two ISO
 * instants the browser computed from the days picked, so a day starts at the
 * viewer's own midnight however the server is set up.
 */
export interface AuditFilters {
  resource?: string;
  action?: string;
  actor?: string;
  period?: AuditPeriod;
  since?: string;
  until?: string;
}

export const AUDIT_FILTER_PARAMS = [
  "resource",
  "action",
  "actor",
  "period",
  "since",
  "until",
] as const satisfies readonly (keyof AuditFilters)[];

type Params = URLSearchParams | Record<string, string | string[] | undefined>;

function read(params: Params, name: string): string | undefined {
  const value =
    params instanceof URLSearchParams ? params.get(name) : params[name];
  return typeof value === "string" && value !== "" ? value : undefined;
}

const isInstant = (value: string | undefined) =>
  value !== undefined && !Number.isNaN(Date.parse(value));

/** The filters a URL asks for; anything it cannot stand for is dropped. */
export function parseAuditFilters(params: Params): AuditFilters {
  const resource = read(params, "resource");
  const action = read(params, "action");
  const period = read(params, "period");
  const since = read(params, "since");
  const until = read(params, "until");
  return {
    resource: (AUDIT_RESOURCE_TYPES as readonly string[]).includes(
      resource ?? ""
    )
      ? resource
      : undefined,
    action: ALL_AUDIT_ACTIONS.includes(action ?? "") ? action : undefined,
    actor: read(params, "actor"),
    period:
      period && Object.hasOwn(AUDIT_PERIODS, period)
        ? (period as AuditPeriod)
        : undefined,
    since: isInstant(since) ? since : undefined,
    until: isInstant(until) ? until : undefined,
  };
}

/** The API query the filters stand for; a relative period ends at `now`. */
export function auditQuery(filters: AuditFilters, now: number): AuditQuery {
  return {
    resource_type: filters.resource,
    action: filters.action,
    actor_id: filters.actor,
    since: filters.period
      ? new Date(now - AUDIT_PERIODS[filters.period]).toISOString()
      : filters.since,
    until: filters.period ? undefined : filters.until,
  };
}

export const isFiltered = (filters: AuditFilters) =>
  AUDIT_FILTER_PARAMS.some((name) => filters[name] !== undefined);

/** A stable key for the filters, e.g. to restart a Suspense boundary on change. */
export const auditFiltersKey = (filters: AuditFilters) =>
  AUDIT_FILTER_PARAMS.map((name) => filters[name] ?? "").join("|");
