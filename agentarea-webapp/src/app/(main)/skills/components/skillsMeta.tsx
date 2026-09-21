import {
  FileText,
  FolderGit2,
  Github,
  Globe,
  Lock,
  Sparkles,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import type { SkillNetworkScope, SkillSourceType } from "@/types/skill";

/**
 * Linear-style metadata for the Skills page. The original design grouped by
 * an invented "category" axis; we map it onto the real data fields instead —
 * `source_type` and `network_scope` — keeping the dense, colour-dotted look.
 */

export interface MetaEntry {
  label: string;
  /** Solid accent colour used for the dot, row glyph and grid icon. */
  color: string;
  icon: LucideIcon;
}

export const SOURCE_META: Record<SkillSourceType, MetaEntry> = {
  content: { label: "Content", color: "#27a08c", icon: FileText },
  github: { label: "GitHub", color: "#2252b3", icon: Github },
  zip: { label: "Uploaded", color: "#d99a00", icon: Upload },
  path: { label: "Local", color: "#0f8c8c", icon: FolderGit2 },
};

export const SCOPE_META: Record<SkillNetworkScope, MetaEntry> = {
  private: { label: "Private", color: "#8a8f98", icon: Lock },
  ingress: { label: "Ingress", color: "#27a08c", icon: Globe },
  egress: { label: "Egress", color: "#d99a00", icon: Globe },
};

export function sourceMeta(type: string): MetaEntry {
  return (
    SOURCE_META[(type as SkillSourceType) ?? "content"] ?? SOURCE_META.content
  );
}

export function scopeMeta(scope: string): MetaEntry {
  return (
    SCOPE_META[(scope as SkillNetworkScope) ?? "private"] ?? SCOPE_META.private
  );
}

/** Order groups appear in when grouping by source / scope. */
export const SOURCE_ORDER: SkillSourceType[] = [
  "content",
  "github",
  "zip",
  "path",
];
export const SCOPE_ORDER: SkillNetworkScope[] = [
  "private",
  "ingress",
  "egress",
];

/**
 * The mark for one skill.
 *
 * Seeded by the skill's own id, not by `source_type`: a workspace whose skills
 * all came from GitHub used to render as one wall of identical blue tiles, with
 * the source spelled out a second time in the pill beside them. Provenance is
 * metadata about a skill, not what distinguishes one skill from another — it
 * keeps the labelled pill and gives the tile back to the skill.
 */
export function SkillTile({
  skillId,
  variant = "row",
}: {
  skillId: string;
  variant?: "row" | "card";
}) {
  const isCard = variant === "card";
  return (
    <EntityAvatar
      size={isCard ? 30 : 22}
      rounded={isCard ? 9 : 7}
      hue={deterministicHue(skillId)}
      icon={<Sparkles strokeWidth={1.85} />}
      aria-hidden
    />
  );
}

/** Compact relative age, e.g. "today", "3d", "2w", "5mo", "1y". */
export function shortAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days < 1) return "today";
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}
