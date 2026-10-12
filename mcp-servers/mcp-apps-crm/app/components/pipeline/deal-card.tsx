import { BoardCard, CardNote } from "@kit/components/board";
import { Chip } from "@kit/components/chip";
import { PersonAvatar } from "@kit/components/person-avatar";
import type { DealRow } from "@shared/schema";
import { Clock } from "lucide-react";
import type { DragEvent } from "react";
import { NextActivityChip } from "@/components/next-activity-chip";
import { formatDate, formatMoneyShort } from "@/lib/format";

export function DealCard({
  deal,
  now,
  saving,
  dragging,
  note,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  deal: DealRow;
  now: string;
  saving: boolean;
  dragging: boolean;
  note: string | undefined;
  onOpen: () => void;
  onDragStart: (event: DragEvent) => void;
  onDragEnd: () => void;
}) {
  const open = deal.status === "open";
  return (
    <BoardCard
      label={deal.title}
      saving={saving}
      dragging={dragging}
      draggable={open}
      onOpen={onOpen}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="text-muted-foreground min-w-0 truncate text-[11px]">
          {deal.company?.name ?? deal.contacts[0]?.name ?? "No company"}
        </span>
        <span className="ml-auto">
          <PersonAvatar person={deal.owner} />
        </span>
      </div>
      <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug font-medium">{deal.title}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <Chip
          className="text-foreground tabular font-medium"
          title={deal.currency === "RUB" ? undefined : `${deal.value} ${deal.currency}`}
        >
          {formatMoneyShort(deal.value, deal.currency)}
        </Chip>
        {open ? (
          <>
            <NextActivityChip deal={deal} now={now} />
            {deal.rotting && (
              <Chip
                tone="danger"
                className="tabular"
                title={`${deal.daysInStage} days in ${deal.stage.name}, longer than the stage allows`}
              >
                <Clock />
                {deal.daysInStage}d in stage
              </Chip>
            )}
          </>
        ) : (
          <>
            {deal.closedAt && <Chip className="tabular">{formatDate(deal.closedAt)}</Chip>}
            {deal.lostReason && (
              <Chip className="min-w-0">
                <span className="truncate">{deal.lostReason}</span>
              </Chip>
            )}
          </>
        )}
      </div>
      <CardNote>{note}</CardNote>
    </BoardCard>
  );
}
