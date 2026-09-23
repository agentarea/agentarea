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
 * Display metadata for the platform's code toolsets, keyed by the namespace an
 * agent stores in `tools[].name`. Mirrors the `@toolset(namespace=...,
 * display_name=...)` declarations in the backend SDK — add an entry here when a
 * toolset is added there, otherwise it renders under its raw namespace.
 */
export const BUILTIN_TOOLSETS: Record<
  string,
  { label: string; icon: LucideIcon }
> = {
  "agentarea/agents": { label: "Agent Management", icon: ENTITY_ICONS.agent },
  "agentarea/audit": { label: "Audit Log", icon: ScrollText },
  "agentarea/clients": {
    label: "Registered Clients",
    icon: ENTITY_ICONS.client,
  },
  "agentarea/context": { label: "Organization Context", icon: Building2 },
  "agentarea/files": { label: "File Operations", icon: FileText },
  "agentarea/inbox": { label: "Inbox", icon: Inbox },
  "agentarea/math": { label: "Math Toolset", icon: Calculator },
  "agentarea/mcp_servers": {
    label: "MCP Server Management",
    icon: ENTITY_ICONS.mcp,
  },
  "agentarea/members": { label: "Workspace Members", icon: Users },
  "agentarea/models": { label: "Models", icon: Brain },
  "agentarea/network": { label: "Network", icon: Network },
  "agentarea/openapi_connections": {
    label: "OpenAPI Connections",
    icon: Webhook,
  },
  "agentarea/policies": { label: "Governance Policies", icon: Shield },
  "agentarea/projects": { label: "Projects", icon: ENTITY_ICONS.project },
  "agentarea/providers": { label: "LLM Providers", icon: Cpu },
  "agentarea/runs": { label: "Agent Runs", icon: Activity },
  "agentarea/secrets": { label: "Secrets", icon: KeyRound },
  "agentarea/shell": { label: "Shell", icon: Terminal },
  "agentarea/skills": { label: "Skills", icon: ENTITY_ICONS.skill },
  "agentarea/triggers": { label: "Triggers", icon: ENTITY_ICONS.trigger },
  "agentarea/web": { label: "Web Tools", icon: Globe },
  "agentarea/workspace_config": { label: "Workspace Config", icon: Settings },
  "agentarea/workspace_files": { label: "Workspace Files", icon: FolderOpen },

  // Pre-namespace tool names, still referenced by older agents and bundles.
  calculator: { label: "Calculator", icon: Calculator },
  math_toolset: { label: "Math Toolset", icon: Calculator },
  file_toolset: { label: "File Operations", icon: FileText },
  web_toolset: { label: "Web Tools", icon: Globe },
};

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  math: Calculator,
  utility: Settings,
  information: Globe,
  platform: ENTITY_ICONS.mcp,
};

/**
 * Icon mapping for different builtin tools
 */
export const getBuiltinToolIcon = (
  toolName: string,
  category?: string
): LucideIcon =>
  BUILTIN_TOOLSETS[toolName]?.icon ??
  (category ? CATEGORY_ICONS[category] : undefined) ??
  ENTITY_ICONS.tool;

/**
 * Human-readable name for a builtin toolset, falling back to the raw namespace
 * so an unmapped toolset is still identifiable rather than blank.
 */
export const getBuiltinToolLabel = (toolName: string): string =>
  BUILTIN_TOOLSETS[toolName]?.label ?? toolName;

/**
 * Get builtin tool display information with icon
 */
export const getBuiltinToolDisplayInfo = (tool: {
  name: string;
  display_name?: string;
  category?: string;
  description?: string;
}) => {
  const IconComponent = getBuiltinToolIcon(tool.name, tool.category);

  return {
    IconComponent,
    displayName: tool.display_name || getBuiltinToolLabel(tool.name),
    description: tool.description || "",
  };
};
