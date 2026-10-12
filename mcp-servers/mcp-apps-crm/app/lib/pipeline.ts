import type { Column, DealRow, PipelineSnapshot } from "@shared/schema";

export type MoveTarget = { stageId: string } | { status: "won" } | { status: "lost"; reason: string };

/** Column totals for the deals on screen, so filters and optimistic moves show at once. */
export function columnsOf(snapshot: PipelineSnapshot, deals: DealRow[]): Column[] {
  return snapshot.pipeline.stages
    .filter((stage) => stage.outcome === null)
    .map((stage) => {
      const inStage = deals.filter((d) => d.status === "open" && d.stage.id === stage.id);
      const total = inStage.reduce((sum, d) => sum + d.baseValue, 0);
      return { stageId: stage.id, count: inStage.length, total, weighted: Math.round(total * stage.probability) };
    });
}

/** The deal as it will look once the move lands. */
export function movedDeal(snapshot: PipelineSnapshot, deal: DealRow, target: MoveTarget): DealRow {
  const stageId = "stageId" in target ? target.stageId : target.status;
  const stage = snapshot.pipeline.stages.find((s) => s.id === stageId || s.outcome === stageId)!;
  return {
    ...deal,
    stage: { id: stage.id, name: stage.name, probability: stage.probability },
    status: stage.outcome ?? "open",
    lostReason: "reason" in target ? target.reason : null,
    closedAt: stage.outcome ? snapshot.now : null,
    daysInStage: 0,
    rotting: false,
  };
}

export const moveArguments = (dealId: string, target: MoveTarget) =>
  "stageId" in target
    ? { deal_id: dealId, stage_id: target.stageId }
    : target.status === "lost"
      ? { deal_id: dealId, status: "lost", lost_reason: target.reason }
      : { deal_id: dealId, status: "won" };
