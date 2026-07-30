import {
  Bot,
  Boxes,
  FolderTree,
  Plug,
  Server,
  Sparkles,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Single source of truth mapping a domain entity to its icon.
 * Use `ENTITY_ICONS[kind]` for a raw Lucide component, or the
 * `<EntityIcon kind="..." />` wrapper for the common styled case.
 */
export const ENTITY_ICONS = {
  agent: Bot,
  mcp: Server,
  skill: Sparkles,
  project: FolderTree,
  client: Plug,
  tool: Wrench,
  trigger: Zap,
  sandbox: Boxes,
} satisfies Record<string, LucideIcon>;

export type EntityKind = keyof typeof ENTITY_ICONS;

export function EntityIcon({
  kind,
  className,
}: {
  kind: EntityKind;
  className?: string;
}) {
  const Icon = ENTITY_ICONS[kind];
  return <Icon className={cn("h-4 w-4", className)} />;
}
