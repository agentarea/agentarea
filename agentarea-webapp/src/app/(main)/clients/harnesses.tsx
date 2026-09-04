import type { ComponentType, SVGProps } from "react";
import { Plug } from "lucide-react";
import { ClaudeIcon, CodexIcon } from "@/components/brand-icons";
import { Badge } from "@/components/ui/badge";

type HarnessGlyph = ComponentType<SVGProps<SVGSVGElement>>;

/**
 * Harness kinds a client can represent. `kind` is set at creation and updated
 * by `agentarea mcp sync --target=<harness>`.
 */
const HARNESSES: Record<string, { label: string; icon: HarnessGlyph }> = {
  claude: { label: "Claude Code", icon: ClaudeIcon },
  "claude-code": { label: "Claude Code", icon: ClaudeIcon },
  codex: { label: "Codex", icon: CodexIcon },
  harness: { label: "Generic", icon: Plug },
};

/** Kinds offered when creating a client, in the order they are shown. */
export const HARNESS_OPTIONS = [
  { value: "harness", label: "Generic" },
  { value: "claude", label: "Claude Code" },
  { value: "codex", label: "Codex" },
];

export const HARNESS_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(HARNESSES).map(([kind, { label }]) => [kind, label])
);

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
