import React from "react";
import {
  Boxes,
  BookOpen,
  Brain,
  Calendar,
  Cloud,
  Code,
  Database,
  FileText,
  FilePlus2,
  Globe,
  Mail,
  MessageSquare,
  Pencil,
  Plug,
  Search,
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

// Order matters: specific action categories precede broad fallbacks.
const RULES: IconRule[] = [
  // Generic action categories. Integration brands use the resolved server icon
  // carried by the event rather than guessing from an arbitrary tool name.
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
  { match: ["edit_file", "apply_patch", "patch"], icon: Pencil },
  { match: ["read_file", "open_file", "cat"], icon: BookOpen },
  { match: ["write_file", "create_file"], icon: FilePlus2 },
  { match: ["file", "document", "read", "write"], icon: FileText },
  { match: ["code", "python", "script", "eval"], icon: Code },
  { match: ["list", "glob", "tree"], icon: Boxes },
];

/**
 * Pick an icon for a tool by its name.
 *
 * Built-in tools map to category icons (shell → CLI terminal, files, search,
 * db, etc.). Actual integration branding is rendered only from an event's
 * resolved icon URL. Namespaced MCP tools without one fall back to a plug.
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
function safeIconUrl(value?: string | null): string | undefined {
  return value && /^(https?:\/\/|\/)/i.test(value) ? value : undefined;
}

export const ToolIcon: React.FC<{
  name?: string | null;
  iconUrl?: string | null;
  className?: string;
}> = ({ name, iconUrl, className }) => {
  const [iconFailed, setIconFailed] = React.useState(false);
  const resolvedUrl = safeIconUrl(iconUrl);
  React.useEffect(() => setIconFailed(false), [resolvedUrl]);

  if (resolvedUrl && !iconFailed) {
    return (
      // Server icons are already resolved catalog assets; avoid remote registry lookups here.
      <img
        src={resolvedUrl}
        alt=""
        width={16}
        height={16}
        className={cn("h-4 w-4 shrink-0 rounded-sm object-contain", className)}
        onError={() => setIconFailed(true)}
      />
    );
  }

  return React.createElement(resolveToolIcon(name), {
    className: cn("h-4 w-4", className),
  });
};

export default ToolIcon;
