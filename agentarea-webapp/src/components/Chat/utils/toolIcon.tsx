import React from "react";
import {
  Boxes,
  Brain,
  Calendar,
  Cloud,
  Code,
  Database,
  FileText,
  Github,
  Globe,
  Mail,
  MessageSquare,
  Plug,
  Search,
  Slack,
  Sparkles,
  SquareTerminal,
  Users,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";

type IconType = React.ComponentType<{ className?: string }>;

interface IconRule {
  /** substrings that, if present in the tool name, select this icon */
  match: string[];
  icon: IconType;
}

// Order matters: brand/service matches first, then generic built-in categories.
const RULES: IconRule[] = [
  // MCP services / brands
  { match: ["github"], icon: Github },
  { match: ["slack"], icon: Slack },
  { match: ["postgres", "mysql", "sqlite", "database", "_sql", "sql_"], icon: Database },
  { match: ["gmail", "email", "smtp", "sendmail"], icon: Mail },
  { match: ["gdrive", "google_drive", "googledrive", "drive_", "s3", "gcs", "storage"], icon: Cloud },
  { match: ["calendar", "gcal", "schedule"], icon: Calendar },
  { match: ["discord", "telegram", "chat_", "message", "notify"], icon: MessageSquare },

  // Built-in tool categories
  { match: ["shell", "bash", "terminal", "command", "cmd", "execute", "exec", "run_"], icon: SquareTerminal },
  { match: ["activate_skill", "skill"], icon: Sparkles },
  { match: ["delegate", "call_agent", "spawn_agent", "sub_agent"], icon: Users },
  { match: ["recall", "memory", "remember", "history"], icon: Brain },
  { match: ["web_search", "google_search", "search", "lookup"], icon: Search },
  { match: ["fetch", "http", "url", "browse", "curl", "request", "web"], icon: Globe },
  { match: ["read_file", "write_file", "edit_file", "file", "document", "read", "write"], icon: FileText },
  { match: ["code", "python", "script", "eval"], icon: Code },
  { match: ["list", "glob", "tree"], icon: Boxes },
];

/**
 * Pick an icon for a tool by its name.
 *
 * Built-in tools map to category icons (shell → CLI terminal, files, search,
 * db, etc.). MCP/brand tools (github_*, slack_*, …) map to the service icon.
 * Anything namespaced as an MCP tool (`mcp__server__tool`) but unrecognized
 * falls back to a generic plug; everything else to a wrench.
 */
export function resolveToolIcon(name?: string | null): IconType {
  if (!name) return Wrench;
  const n = name.toLowerCase();

  for (const rule of RULES) {
    if (rule.match.some((m) => n.includes(m))) return rule.icon;
  }

  // Unrecognized MCP-namespaced tool (mcp__server__tool) → generic service plug.
  if (n.startsWith("mcp__") || n.includes("__")) return Plug;

  return Wrench;
}

/** Render the icon for a given tool name. */
export const ToolIcon: React.FC<{ name?: string | null; className?: string }> = ({
  name,
  className,
}) => {
  const Icon = resolveToolIcon(name);
  return <Icon className={cn("h-4 w-4", className)} />;
};

export default ToolIcon;
