import {
  Activity,
  Brain,
  Building2,
  Calculator,
  Cpu,
  FileText,
  FolderOpen,
  Globe,
  Inbox,
  KeyRound,
  LucideIcon,
  Network,
  ScrollText,
  Settings,
  Shield,
  Terminal,
  Users,
  Webhook,
} from "lucide-react";
import { ENTITY_ICONS } from "@/lib/entity-icons";

/**
 * Icon per code toolset, keyed by the namespace an agent stores in
 * `tools[].name`.
 *
 * Icons are the one piece of toolset presentation the backend cannot send: a
 * lucide component does not travel over the wire. Everything else about a
 * toolset — label, category, plane, its methods — comes from
 * `GET /v1/agents/tools`, so this map must never grow a `label` again. A
 * toolset missing here falls back by category and then to a generic tool icon;
 * it still renders under its real name.
 */
export const TOOLSET_ICONS: Record<string, LucideIcon> = {
  "agentarea/agents": ENTITY_ICONS.agent,
  "agentarea/audit": ScrollText,
  "agentarea/clients": ENTITY_ICONS.client,
  "agentarea/context": Building2,
  "agentarea/files": FileText,
  "agentarea/inbox": Inbox,
  "agentarea/math": Calculator,
  "agentarea/mcp_servers": ENTITY_ICONS.mcp,
  "agentarea/members": Users,
  "agentarea/models": Brain,
  "agentarea/network": Network,
  "agentarea/openapi_connections": Webhook,
  "agentarea/policies": Shield,
  "agentarea/projects": ENTITY_ICONS.project,
  "agentarea/providers": Cpu,
  "agentarea/runs": Activity,
  "agentarea/secrets": KeyRound,
  "agentarea/shell": Terminal,
  "agentarea/skills": ENTITY_ICONS.skill,
  "agentarea/triggers": ENTITY_ICONS.trigger,
  "agentarea/web": Globe,
  "agentarea/workspace_config": Settings,
  "agentarea/workspace_files": FolderOpen,

  // Pre-namespace tool names, still referenced by older agents and bundles.
  calculator: Calculator,
  math_toolset: Calculator,
  file_toolset: FileText,
  web_toolset: Globe,
};

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  math: Calculator,
  utility: Settings,
  information: Globe,
  platform: ENTITY_ICONS.mcp,
};

/** Words the backend spells as initialisms; naive casing mangles them. */
const INITIALISMS: Record<string, string> = {
  api: "API",
  llm: "LLM",
  mcp: "MCP",
  openapi: "OpenAPI",
};

export const getBuiltinToolIcon = (
  toolName: string,
  category?: string
): LucideIcon =>
  TOOLSET_ICONS[toolName] ??
  (category ? CATEGORY_ICONS[category] : undefined) ??
  ENTITY_ICONS.tool;

/**
 * Readable name for a toolset when only its namespace is at hand.
 *
 * Prefer the API's `display_name`. This derivation exists for the places that
 * render an agent's stored `tools[].name` without having fetched the catalog
 * (tool chips on cards and panels) — a title-cased namespace beats both a raw
 * `agentarea/workspace_files` and a hand-kept copy of the registry.
 *
 * Only our own namespaces are rewritten. A third-party `vendor/thing` keeps its
 * raw name: dropping the publisher would leave "Thing", which reads as a UI
 * failure rather than as somebody else's toolset.
 */
export const getBuiltinToolLabel = (toolName: string): string => {
  const [publisher, name] = toolName.includes("/")
    ? toolName.split("/")
    : ["agentarea", toolName];
  if (publisher !== "agentarea") return toolName;

  return name
    .replace(/_toolset$/, "")
    .split("_")
    .filter(Boolean)
    .map((word) => INITIALISMS[word] ?? word[0].toUpperCase() + word.slice(1))
    .join(" ");
};

/** Icon, label and description for one catalog entry. */
export const getBuiltinToolDisplayInfo = (tool: {
  name: string;
  display_name?: string;
  category?: string;
  description?: string;
}) => ({
  IconComponent: getBuiltinToolIcon(tool.name, tool.category),
  displayName: tool.display_name || getBuiltinToolLabel(tool.name),
  description: tool.description || "",
});
