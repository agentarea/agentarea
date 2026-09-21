// Agent visual identity: which glyph an agent wears and which hue tints it.
//
// Colour is derived from the agent's id and nothing else — see
// `@/lib/avatar-hue` for the ramp. The glyph is *not*: it used to be picked by
// the same hash, which handed the researcher a pickaxe and the guard a
// calculator, and a wrong-on-purpose icon reads as a bug rather than as
// identity. The curated set below is what a picker offers; until an agent has
// been given one, every agent wears the same neutral `bot`.

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
  type LucideIcon,
} from "lucide-react";
import {
  deterministicHue,
  isAvatarHue,
  type AvatarHue,
} from "@/lib/avatar-hue";

/** The glyph an agent wears when it has not been given one. */
export const DEFAULT_AGENT_ICON = "bot";

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

export interface AgentIdentityInput {
  id: string;
  name?: string | null;
  /** A key from `AGENT_ICONS`, once the agent has been given one. */
  icon?: string | null;
  /** A name from the avatar ramp, once the agent has been given one. */
  hue?: string | null;
}

export function resolveAgentIdentity(agent: AgentIdentityInput): {
  hue: AvatarHue;
  iconKey: string;
} {
  return {
    hue: isAvatarHue(agent.hue)
      ? agent.hue
      : deterministicHue(agent.id || agent.name || "agent"),
    iconKey:
      agent.icon && ICON_BY_KEY[agent.icon] ? agent.icon : DEFAULT_AGENT_ICON,
  };
}

export function getAgentIconComponent(iconKey: string): LucideIcon {
  return ICON_BY_KEY[iconKey] ?? Bot;
}
