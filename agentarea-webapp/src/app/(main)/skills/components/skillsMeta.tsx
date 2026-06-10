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
  /** Key under the `SkillsPage.view` namespace for the localized label. */
  labelKey: string;
  /** Solid accent colour used for the dot, row glyph and grid icon. */
  color: string;
  icon: LucideIcon;
}

export const SOURCE_META: Record<SkillSourceType, MetaEntry> = {
  content: { labelKey: "sourceContent", color: "#27a08c", icon: FileText },
  github: { labelKey: "sourceGithub", color: "#5e6ad2", icon: Github },
  zip: { labelKey: "sourceUploaded", color: "#d99a00", icon: Upload },
  path: { labelKey: "sourceLocal", color: "#d4519e", icon: FolderGit2 },
};

export const SCOPE_META: Record<SkillNetworkScope, MetaEntry> = {
  private: { labelKey: "scopePrivate", color: "#8a8f98", icon: Lock },
  ingress: { labelKey: "scopeIngress", color: "#27a08c", icon: Globe },
  egress: { labelKey: "scopeEgress", color: "#d99a00", icon: Globe },
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

// The brand glyph tile (`Tile`) and `shortAge` now live in the reusable
// `@/components/CollectionView` — import them from there.
