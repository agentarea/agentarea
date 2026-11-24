import type { ComponentType, SVGProps } from "react";
import { Plug, SquareTerminal } from "lucide-react";
import type { AgentClientSummary } from "@/api/client";
import { ClaudeIcon, CodexIcon } from "@/components/brand-icons";
import { Badge } from "@/components/ui/badge";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";

type HarnessGlyph = ComponentType<SVGProps<SVGSVGElement>>;

/**
 * Harness kinds a client can represent. `kind` is set at creation and updated
 * by `agentarea mcp sync --target=<harness>`.
 */
const HARNESSES: Record<string, { label: string; icon: HarnessGlyph }> = {
  claude: { label: "Claude Code", icon: ClaudeIcon },
  "claude-code": { label: "Claude Code", icon: ClaudeIcon },
  codex: { label: "Codex", icon: CodexIcon },
  opencode: { label: "OpenCode", icon: SquareTerminal },
  gemini: { label: "Gemini CLI", icon: SquareTerminal },
  qwen: { label: "Qwen Code", icon: SquareTerminal },
  goose: { label: "Goose", icon: SquareTerminal },
  cursor: { label: "Cursor", icon: SquareTerminal },
  acp: { label: "Custom ACP command", icon: SquareTerminal },
  harness: { label: "Generic", icon: Plug },
};

/** Kinds offered when creating a client, in the order they are shown. */
export const HARNESS_OPTIONS = [
  { value: "harness", label: "Generic" },
  { value: "claude", label: "Claude Code" },
  { value: "codex", label: "Codex" },
  { value: "opencode", label: "OpenCode" },
  { value: "gemini", label: "Gemini CLI" },
  { value: "qwen", label: "Qwen Code" },
  { value: "goose", label: "Goose" },
  { value: "cursor", label: "Cursor" },
  { value: "acp", label: "Custom ACP command" },
];

export function harnessOf(kind?: string | null) {
  return HARNESSES[kind ?? ""] ?? { label: kind || "Generic", icon: Plug };
}

export function HarnessIcon({
  kind,
  className,
}: {
  kind?: string | null;
  className?: string;
}) {
  const { icon: Icon } = harnessOf(kind);
  return <Icon aria-hidden="true" className={className} />;
}

export function HarnessBadge({ kind }: { kind?: string | null }) {
  return (
    <Badge variant="outline" className="text-xs">
      {harnessOf(kind).label}
    </Badge>
  );
}

/** The client an agent runs on, linking to its page. */
export function HarnessClientLink({
  client,
  withIcon = true,
  className,
}: {
  client: Pick<AgentClientSummary, "id" | "kind" | "name">;
  withIcon?: boolean;
  className?: string;
}) {
  return (
    <Link
      href={`/clients/${client.id}`}
      className={cn(
        "inline-flex min-w-0 max-w-full items-center gap-1 rounded-sm text-foreground/80 hover:text-foreground hover:underline",
        className
      )}
    >
      {withIcon && (
        <HarnessIcon kind={client.kind} className="h-3.5 w-3.5 shrink-0" />
      )}
      <span className="truncate">{client.name}</span>
    </Link>
  );
}
