import { StatusGlyph } from "@kit/components/glyphs";
import type { DealRow, Stage } from "@shared/schema";
import { stageGlyph } from "@/lib/meta";

export function StageIcon({ stage, className }: { stage: Pick<Stage, "probability" | "outcome">; className?: string }) {
  return <StatusGlyph {...stageGlyph(stage)} className={className} />;
}

/** The glyph of where a deal stands: its open stage, or won / lost. */
export function DealStageIcon({ deal, className }: { deal: DealRow; className?: string }) {
  return (
    <StageIcon
      stage={{ probability: deal.stage.probability, outcome: deal.status === "open" ? null : deal.status }}
      className={className}
    />
  );
}
