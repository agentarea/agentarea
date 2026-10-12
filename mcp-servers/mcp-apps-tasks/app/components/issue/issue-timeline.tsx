import { Section } from "@kit/components/section";
import { Composer, Strong, Timeline, TimelineCard, TimelineEvent, When as KitWhen } from "@kit/components/timeline";
import type { ActivityEntry, CommentEntry, TaskDetail } from "@shared/schema";
import type { Priority, Status } from "@shared/tasks";
import type { ReactNode } from "react";
import { StatusIcon } from "@/components/status-icon";
import { formatDateTime, formatDay, timeAgo } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { PRIORITY_META, STATUS_META } from "@/lib/meta";
import type { FieldState, IssueActions } from "./types";

type Item =
  { at: string; activity: ActivityEntry; comment?: never } | { at: string; comment: CommentEntry; activity?: never };

function StatusName({ status }: { status: string | null }) {
  if (!status || !(status in STATUS_META)) return <Strong>{status ?? "none"}</Strong>;
  return (
    <span className="text-foreground inline-flex items-center gap-1 align-[-2px] font-medium">
      <StatusIcon status={status as Status} className="size-3" />
      {STATUS_META[status as Status].label}
    </span>
  );
}

/** One activity entry as a sentence: "moved from Todo to In progress". */
function describe(entry: ActivityEntry, now: string): ReactNode {
  const { kind, from, to } = entry;
  switch (kind) {
    case "created":
      return (
        <>
          created the issue
          {to && (
            <>
              {" "}
              in <StatusName status={to} />
            </>
          )}
        </>
      );
    case "status":
      return (
        <>
          moved from <StatusName status={from} /> to <StatusName status={to} />
        </>
      );
    case "priority":
      return (
        <>
          changed priority from <Strong>{PRIORITY_META[from as Priority]?.label ?? from}</Strong> to{" "}
          <Strong>{PRIORITY_META[to as Priority]?.label ?? to}</Strong>
        </>
      );
    case "assignee":
      if (!to)
        return (
          <>
            unassigned <Strong>{from}</Strong>
          </>
        );
      if (to === entry.actor.name && !from) return <>self-assigned the issue</>;
      return from ? (
        <>
          reassigned from <Strong>{from}</Strong> to <Strong>{to}</Strong>
        </>
      ) : (
        <>
          assigned <Strong>{to}</Strong>
        </>
      );
    case "due":
      return to ? (
        <>
          set the due date to <Strong>{formatDay(to, now)}</Strong>
        </>
      ) : (
        <>removed the due date</>
      );
    case "labels":
      return to ? (
        <>
          set labels to <Strong>{to}</Strong>
        </>
      ) : (
        <>removed all labels</>
      );
    case "title":
      return (
        <>
          renamed the issue to <Strong>{to}</Strong>
        </>
      );
    case "description":
      return <>edited the description</>;
    case "estimate":
      return to ? (
        <>
          set the estimate to <Strong>{to} points</Strong>
        </>
      ) : (
        <>removed the estimate</>
      );
    case "parent":
      return to ? (
        <>
          made it a sub-issue of <Strong>{to}</Strong>
        </>
      ) : (
        <>
          detached it from <Strong>{from}</Strong>
        </>
      );
  }
}

function When({ at, now }: { at: string; now: string }) {
  return <KitWhen at={at} label={timeAgo(at, now)} title={formatDateTime(at)} />;
}

/** Activity and comments as one chronological stream, newest last, with the comment box under it. */
export function IssueTimeline({
  card,
  state,
  onComment,
}: {
  card: TaskDetail;
  state: FieldState;
  onComment: IssueActions["onComment"];
}) {
  const items: Item[] = [
    ...card.activity.map((activity) => ({ at: activity.at, activity })),
    ...card.commentList.map((comment) => ({ at: comment.createdAt, comment })),
  ].toSorted((a, b) => a.at.localeCompare(b.at));

  return (
    <Section title="Activity" className="gap-3">
      <Timeline>
        {items.map((item) =>
          item.comment ? (
            <TimelineCard
              key={item.comment.id}
              author={item.comment.author}
              when={<When at={item.at} now={card.now} />}
            >
              <Markdown text={item.comment.body} />
            </TimelineCard>
          ) : (
            <TimelineEvent
              key={item.activity.id}
              actor={item.activity.actor}
              when={<When at={item.at} now={card.now} />}
            >
              <Strong>{item.activity.actor.name}</Strong> {describe(item.activity, card.now)}
            </TimelineEvent>
          ),
        )}
      </Timeline>
      <Composer
        placeholder="Leave a comment…"
        label="Comment"
        submitLabel="Comment"
        busy={state.busy.comment}
        note={state.notes.comment}
        onSubmit={onComment}
      />
    </Section>
  );
}
