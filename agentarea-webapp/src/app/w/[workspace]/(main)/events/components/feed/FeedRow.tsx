"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Paperclip } from "lucide-react";
import type { FeedEventResponse } from "@/api/client/types.gen";
import { AgentAvatar, type AgentAvatarAgent } from "@/components/AgentAvatar";
import EventTime from "@/components/EventTime";
import SourceTypeMark from "@/components/SourceTypeMark";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  eventFate,
  PLATFORM_SOURCE_TYPE,
  platformOutcome,
  type EventFate,
} from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import type { StatusKind } from "@/lib/status";
import { cn } from "@/lib/utils";

export type FeedAgent = AgentAvatarAgent & { name: string };

const FATE_KIND: Record<
  Exclude<EventFate["key"], "tasks" | "nobody">,
  StatusKind
> = {
  queued: "queued",
  processing: "running",
  skipped: "off",
  passedOn: "done",
  failed: "failed",
};

/**
 * One thing that happened, on one line of a log: when, what it was, where it
 * came from, and what became of it. A task's event names its agent and its
 * outcome. An event nobody handles is a plain record: its last cell is empty.
 */
export default function FeedRow({
  event,
  count,
  sourceTypes,
  agents,
  streamName,
  selected,
  onOpen,
}: {
  event: FeedEventResponse;
  /** How many alike events the row stands for; opening it unfolds them. */
  count: number;
  sourceTypes: SourceType[];
  agents: Map<string, FeedAgent>;
  /** Shown when the feed spans several streams. */
  streamName: string | null;
  selected: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("EventsPage.row");
  const outcome =
    event.source_type === PLATFORM_SOURCE_TYPE
      ? platformOutcome(event.kind)
      : null;
  const agent = outcome && event.sender ? agents.get(event.sender) : undefined;
  const type = sourceTypeBySlug(sourceTypes, event.source_type);

  let glyph: ReactNode;
  let what: string;
  let detail: string | null;
  let where: string | null;
  let result: ReactNode = null;

  if (outcome) {
    glyph = agent ? (
      <AgentAvatar agent={agent} size="xs" />
    ) : (
      <StatusIndicator size="sm" kind={outcome.status} />
    );
    what = agent?.name ?? t(`task.${outcome.key}`);
    detail = event.summary;
    where = null;
    result = agent && (
      <StatusIndicator size="sm" kind={outcome.status}>
        {t(`task.${outcome.key}`)}
      </StatusIndicator>
    );
  } else {
    glyph = (
      <SourceTypeMark
        type={type}
        slug={event.source_type}
        inline
        className="h-3.5 w-3.5"
      />
    );
    what = event.summary ?? event.kind;
    const source = type?.name ?? event.source_type;
    const kindSaysMore =
      event.summary !== null &&
      event.kind.toLowerCase() !== source?.toLowerCase();
    detail = [kindSaysMore ? event.kind : null, event.sender]
      .filter(Boolean)
      .join(" · ");
    where =
      [source?.toLowerCase() === what.toLowerCase() ? null : source, streamName]
        .filter(Boolean)
        .join(" · ") || null;
    const fate = eventFate(event.processing);
    if (fate.key !== "nobody") {
      result = (
        <StatusIndicator
          size="sm"
          kind={fate.key === "tasks" ? fate.status : FATE_KIND[fate.key]}
        >
          {fate.key === "tasks"
            ? t("fate.tasks", {
                count: fate.count,
                status: t(`taskStatus.${fate.status}`),
              })
            : fate.key === "failed"
              ? t("fate.failed", { count: fate.count })
              : t(`fate.${fate.key}`)}
        </StatusIndicator>
      );
    }
  }

  return (
    <InteractiveListRow
      onClick={onOpen}
      selected={selected}
      showIndicator={false}
      className="gap-3 py-1.5 text-[13px]"
      start={
        <span className="w-10 font-mono text-[12px] text-muted-foreground tabular-nums">
          <EventTime value={event.received_at} style="time" />
        </span>
      }
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="grid h-5 w-5 shrink-0 place-items-center">
          {glyph}
        </span>
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <span className="min-w-0 shrink truncate font-medium md:max-w-[60%] md:shrink-0">
            {what}
          </span>
          <Count count={count} />
          {event.attachments > 0 && (
            <Paperclip
              aria-label={t("attachments")}
              className="h-3 w-3 shrink-0 text-muted-foreground"
            />
          )}
          {detail && (
            <span className="min-w-0 truncate text-muted-foreground">
              {detail}
            </span>
          )}
        </span>
        <span className="hidden w-40 shrink-0 truncate text-[12px] text-muted-foreground md:block">
          {where}
        </span>
        <span
          className={cn(
            "shrink-0 justify-end text-[12px] md:flex md:w-44",
            result ? "flex" : "hidden"
          )}
        >
          {result}
        </span>
      </div>
    </InteractiveListRow>
  );
}

function Count({ count }: { count: number }) {
  if (count < 2) return null;
  return (
    <span className="shrink-0 rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground tabular-nums">
      ×{count}
    </span>
  );
}
