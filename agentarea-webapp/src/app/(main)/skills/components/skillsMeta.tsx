import {
  FileText,
  FolderGit2,
  Github,
  Globe,
  Lock,
  Upload,
  type LucideIcon,
} from "lucide-react";
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
  github: { label: "GitHub", color: "#5e6ad2", icon: Github },
  zip: { label: "Uploaded", color: "#d99a00", icon: Upload },
  path: { label: "Local", color: "#d4519e", icon: FolderGit2 },
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
 * Skill glyph tile — the brand "skill" icon. A softly category-tinted square
 * (13% colour over the surface) with a matching 26% border and the source
 * glyph in full colour.
 */
export function SkillTile({
  color,
  icon: Icon,
  variant = "row",
}: {
  color: string;
  icon: LucideIcon;
  variant?: "row" | "card";
}) {
  const isCard = variant === "card";
  const box = isCard ? 30 : 22;
  const radius = isCard ? 8 : 6;
  const glyph = isCard ? 17 : 13;
  return (
    <span
      className="relative flex shrink-0 items-center justify-center border"
      style={{
        width: box,
        height: box,
        borderRadius: radius,
        color,
        background: `color-mix(in srgb, ${color} 13%, var(--tile-base))`,
        borderColor: `color-mix(in srgb, ${color} 26%, var(--tile-base))`,
      }}
    >
      <Icon style={{ width: glyph, height: glyph }} strokeWidth={1.9} />
    </span>
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
