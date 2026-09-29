import {
  Brain,
  ClipboardList,
  FilePlus2,
  Globe,
  KeyRound,
  Pencil,
  ShieldCheck,
  Trash2,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { ENTITY_ICONS } from "@/lib/entity-icons";

/**
 * A glyph per audited resource type, so a page of log lines can be scanned for
 * "what kind of thing" without reading every row. Types come from the API's
 * `resource_type`; anything unmapped simply gets no icon rather than a
 * stand-in that would imply the wrong kind.
 */
const RESOURCE_ICONS: Record<string, LucideIcon> = {
  agent: ENTITY_ICONS.agent,
  task: ClipboardList,
  trigger: ENTITY_ICONS.trigger,
  skill: ENTITY_ICONS.skill,
  mcp_server: ENTITY_ICONS.mcp,
  mcp_instance: ENTITY_ICONS.mcp,
  governance_policy: ShieldCheck,
  policy: ShieldCheck,
  project: ENTITY_ICONS.project,
  openapi_connection: Globe,
  provider_config: Brain,
  api_key: KeyRound,
  client: ENTITY_ICONS.client,
  secret: KeyRound,
};

export function auditResourceIcon(type: string): LucideIcon | null {
  return RESOURCE_ICONS[type] ?? null;
}

const VERB_ICONS: Record<string, LucideIcon> = {
  create: FilePlus2,
  update: Pencil,
  delete: Trash2,
};

export function auditVerbIcon(verb: string): LucideIcon | null {
  return VERB_ICONS[verb] ?? null;
}

/**
 * Who did it. An actor is a person unless the id names one of our own
 * runtime principals, which is the distinction the log was missing: every
 * row read as an anonymous id regardless of whether a human or an agent
 * did the thing.
 */
export function auditActorIcon(actorType?: string | null): LucideIcon {
  if (actorType === "agent") return ENTITY_ICONS.agent;
  if (actorType === "client") return ENTITY_ICONS.client;
  if (actorType === "api_key") return KeyRound;
  return UserRound;
}
