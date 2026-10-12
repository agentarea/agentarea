import { BoardColumn, BoardScroller, useBoardDrag } from "@kit/components/board";
import { StageIcon } from "@/components/stage-icon";
import { LostReasonForm } from "@/components/lost-reason-form";
import { formatMoneyShort, formatPercent } from "@/lib/format";
import { DealCard } from "./deal-card";
import { stageGroups } from "./grouping";
import { NewDealForm } from "./new-deal-form";
import type { PipelineViewProps } from "./types";

/** One column per stage, then Won and Lost. Drag a deal to move it; dropping on Lost asks why. */
export function PipelineBoard(props: PipelineViewProps) {
  const { snapshot, deals, saving, notes, composing, onCompose, onCreate, onOpen, onMove } = props;
  const { losing, lossBusy, lossError, onAskLost, onCancelLost } = props;
  const drag = useBoardDrag<string>((dealId, stageId) => {
    const deal = deals.find((d) => d.id === dealId);
    const stage = snapshot.pipeline.stages.find((s) => s.id === stageId);
    if (!deal || !stage || deal.status !== "open") return;
    if (stage.outcome === "won") onMove(deal, { status: "won" });
    else if (stage.outcome === "lost") onAskLost(deal);
    else if (deal.stage.id !== stage.id) onMove(deal, { stageId: stage.id });
  });

  return (
    <BoardScroller>
      {stageGroups(snapshot, deals).map(({ stage, deals: column, total }) => {
        const closed = stage.outcome !== null;
        const asking = stage.outcome === "lost" && losing;
        return (
          <BoardColumn
            key={stage.id}
            title={stage.name}
            glyph={<StageIcon stage={stage} />}
            count={column.length}
            meta={
              <span
                title={
                  closed
                    ? `Total in ${snapshot.baseCurrency}`
                    : `Total in ${snapshot.baseCurrency}; ${formatPercent(stage.probability)} win probability`
                }
              >
                {formatMoneyShort(total, snapshot.baseCurrency)}
              </span>
            }
            addLabel={closed ? undefined : `New deal in ${stage.name}`}
            onAdd={closed ? undefined : () => onCompose(composing === stage.id ? null : stage.id)}
            drop={drag.column(stage.id)}
            empty={
              column.length === 0 && composing !== stage.id && !asking
                ? closed
                  ? `Drop a deal here: ${stage.name.toLowerCase()}`
                  : "No deals"
                : undefined
            }
          >
            {composing === stage.id && (
              <NewDealForm snapshot={snapshot} stage={stage} onCreate={onCreate} onClose={() => onCompose(null)} />
            )}
            {asking && (
              <LostReasonForm
                key={losing.id}
                title={losing.title}
                reasons={snapshot.lostReasons}
                busy={lossBusy}
                error={lossError}
                onConfirm={(reason) => onMove(losing, { status: "lost", reason })}
                onCancel={onCancelLost}
              />
            )}
            {column.map((deal) => (
              <DealCard
                key={deal.id}
                deal={deal}
                now={snapshot.now}
                saving={saving[deal.id] ?? false}
                note={notes[deal.id]}
                onOpen={() => onOpen(deal)}
                {...drag.card(deal.id)}
              />
            ))}
          </BoardColumn>
        );
      })}
    </BoardScroller>
  );
}
