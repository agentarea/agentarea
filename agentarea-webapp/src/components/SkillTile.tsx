import { Sparkles } from "lucide-react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";

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
