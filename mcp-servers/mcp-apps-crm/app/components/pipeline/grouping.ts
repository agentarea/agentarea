import type { DealRow, PipelineSnapshot, Stage } from "@shared/schema";

/** Every stage of the pipeline with its deals: open stages in order, then Won and Lost. */
export function stageGroups(
  snapshot: PipelineSnapshot,
  deals: DealRow[],
): { stage: Stage; deals: DealRow[]; total: number }[] {
  return snapshot.pipeline.stages.map((stage) => {
    const inStage = deals
      .filter((d) => (stage.outcome ? d.status === stage.outcome : d.status === "open" && d.stage.id === stage.id))
      .toSorted((a, b) =>
        stage.outcome
          ? (b.closedAt ?? "").localeCompare(a.closedAt ?? "")
          : Number(b.rotting) - Number(a.rotting) || b.baseValue - a.baseValue,
      );
    return { stage, deals: inStage, total: inStage.reduce((sum, d) => sum + d.baseValue, 0) };
  });
}
