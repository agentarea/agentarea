import { Chip } from "@kit/components/chip";
import { ListEmpty, ListFrame, ListGroup, ListRow, ListRowNote } from "@kit/components/list";
import { PersonAvatar } from "@kit/components/person-avatar";
import { Fragment } from "react";
import { CalendarClock } from "lucide-react";
import { NextActivityChip } from "@/components/next-activity-chip";
import { DealStageIcon, StageIcon } from "@/components/stage-icon";
import { formatDate, formatDay, formatMoneyShort } from "@/lib/format";
import { stageGroups } from "./grouping";
import { NewDealForm } from "./new-deal-form";
import type { PipelineViewProps } from "./types";

/** The same deals as the board, as one list grouped by stage. */
export function DealList(props: PipelineViewProps) {
  const { snapshot, deals, saving, notes, composing, onCompose, onCreate, onOpen } = props;
  const groups = stageGroups(snapshot, deals).filter((g) => g.deals.length > 0 || composing === g.stage.id);

  if (groups.length === 0) return <ListEmpty>No deals match.</ListEmpty>;

  return (
    <ListFrame>
      {groups.map(({ stage, deals: rows, total }) => {
        const closed = stage.outcome !== null;
        return (
          <ListGroup
            key={stage.id}
            title={stage.name}
            glyph={<StageIcon stage={stage} />}
            count={rows.length}
            meta={formatMoneyShort(total, snapshot.baseCurrency)}
            addLabel={closed ? undefined : `New deal in ${stage.name}`}
            onAdd={closed ? undefined : () => onCompose(composing === stage.id ? null : stage.id)}
          >
            {composing === stage.id && (
              <div className="border-b p-2">
                <NewDealForm snapshot={snapshot} stage={stage} onCreate={onCreate} onClose={() => onCompose(null)} />
              </div>
            )}
            {rows.map((deal) => (
              <Fragment key={deal.id}>
                <ListRow saving={saving[deal.id] ?? false} onOpen={() => onOpen(deal)}>
                  <DealStageIcon deal={deal} />
                  <span className="min-w-0 flex-1 truncate">
                    {deal.title}
                    <span className="text-muted-foreground hidden sm:inline">
                      {" "}
                      · {deal.company?.name ?? "No company"}
                    </span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-1 md:flex">
                    {closed ? (
                      <>
                        {deal.lostReason && (
                          <Chip className="max-w-[200px]">
                            <span className="truncate">{deal.lostReason}</span>
                          </Chip>
                        )}
                        {deal.closedAt && <Chip className="tabular">{formatDate(deal.closedAt)}</Chip>}
                      </>
                    ) : (
                      <>
                        {deal.rotting && (
                          <Chip tone="danger" className="tabular">
                            {deal.daysInStage}d in stage
                          </Chip>
                        )}
                        <NextActivityChip deal={deal} now={snapshot.now} />
                        {deal.expectedCloseDate && (
                          <Chip className="tabular" title="Expected close">
                            <CalendarClock />
                            {formatDay(deal.expectedCloseDate).replace(/, \d{4}$/, "")}
                          </Chip>
                        )}
                      </>
                    )}
                  </span>
                  <span className="tabular w-[72px] shrink-0 text-right font-medium">
                    {formatMoneyShort(deal.value, deal.currency)}
                  </span>
                  <PersonAvatar person={deal.owner} />
                </ListRow>
                <ListRowNote>{notes[deal.id]}</ListRowNote>
              </Fragment>
            ))}
          </ListGroup>
        );
      })}
    </ListFrame>
  );
}
