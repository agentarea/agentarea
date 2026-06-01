// Agent visual identity helpers.
//
// Identity is layered:
//   1. Deterministic-from-id colour + icon (free; works without any backend
//      change — used as fallback)
//   2. User-overridden icon and colour (planned: agents.icon /
//      agents.color_token columns; see follow-up)
//
// Public API:
//   - resolveAgentIdentity(agent) → { color, iconKey }
//   - AGENT_ICONS (the curated Lucide set the picker exposes)
//   - getAgentIconComponent(iconKey) → Lucide component

import {
  Bot,
  Brain,
  Briefcase,
  Calculator,
  Code2,
  Compass,
  FileText,
  GitBranch,
  Headphones,
  Languages,
  type LucideIcon,
  Mailbox,
  Pencil,
  Pickaxe,
  Rocket,
  ScanEye,
  Search,
  Shield,
  Sparkles,
  Wrench,
  Zap,
} from "lucide-react";

// Curated Lucide subset for the picker. Names are what we'd surface in UI;
// keys are stable strings stored on the agent (never localise these).
export const AGENT_ICONS: { key: string; label: string; Icon: LucideIcon }[] = [
  { key: "bot", label: "Bot", Icon: Bot },
  { key: "sparkles", label: "Sparkles", Icon: Sparkles },
  { key: "brain", label: "Brain", Icon: Brain },
  { key: "search", label: "Researcher", Icon: Search },
  { key: "scan", label: "Scanner", Icon: ScanEye },
  { key: "compass", label: "Compass", Icon: Compass },
  { key: "rocket", label: "Launcher", Icon: Rocket },
  { key: "code", label: "Coder", Icon: Code2 },
  { key: "git", label: "Branch", Icon: GitBranch },
  { key: "wrench", label: "Wrench", Icon: Wrench },
  { key: "pickaxe", label: "Miner", Icon: Pickaxe },
  { key: "pen", label: "Writer", Icon: Pencil },
  { key: "doc", label: "Docs", Icon: FileText },
  { key: "translate", label: "Translator", Icon: Languages },
  { key: "calc", label: "Calculator", Icon: Calculator },
  { key: "support", label: "Support", Icon: Headphones },
  { key: "mailbox", label: "Inbox", Icon: Mailbox },
  { key: "shield", label: "Guard", Icon: Shield },
  { key: "briefcase", label: "Manager", Icon: Briefcase },
  { key: "zap", label: "Trigger", Icon: Zap },
];

const ICON_BY_KEY: Record<string, LucideIcon> = Object.fromEntries(
  AGENT_ICONS.map((i) => [i.key, i.Icon])
);

// Token names from `tailwind.config.ts` — each maps to a real CSS variable.
export const AGENT_COLOR_TOKENS = [
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "primary",
  "accent",
] as const;
export type AgentColorToken = (typeof AGENT_COLOR_TOKENS)[number];

function hash(str: string): number {
  // djb2-ish — small but well-distributed for our 7-colour space.
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function resolveAgentIdentity(agent: {
  id: string;
  name?: string | null;
  icon?: string | null;
  color_token?: string | null;
}): { colorToken: AgentColorToken; iconKey: string } {
  const seed = hash(agent.id || agent.name || "agent");
  const fallbackColor = AGENT_COLOR_TOKENS[seed % AGENT_COLOR_TOKENS.length];
  const fallbackIcon = AGENT_ICONS[seed % AGENT_ICONS.length].key;

  const colorToken = (
    agent.color_token && AGENT_COLOR_TOKENS.includes(agent.color_token as AgentColorToken)
      ? agent.color_token
      : fallbackColor
  ) as AgentColorToken;
  const iconKey =
    agent.icon && ICON_BY_KEY[agent.icon] ? agent.icon : fallbackIcon;

  return { colorToken, iconKey };
}

export function getAgentIconComponent(iconKey: string): LucideIcon {
  return ICON_BY_KEY[iconKey] ?? Bot;
}

// Helper for inline styles — gets the HSL from the CSS variable so
// custom colours mix with the theme cleanly.
export function agentColorVar(token: AgentColorToken): string {
  return `hsl(var(--${token}))`;
}

export function agentColorVarSoft(token: AgentColorToken, alpha = 0.15): string {
  return `hsl(var(--${token}) / ${alpha})`;
}
