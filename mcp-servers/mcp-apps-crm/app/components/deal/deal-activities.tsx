import { Chip } from "@kit/components/chip";
import { Callout, FieldNote } from "@kit/components/notes";
import { PersonAvatar } from "@kit/components/person-avatar";
import { Section } from "@kit/components/section";
import { Strong, Timeline, TimelineCard, TimelineEvent, When } from "@kit/components/timeline";
import { timeAgo } from "@kit/lib/format";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
import { Textarea } from "@kit/ui/textarea";
import { ACTIVITY_TYPES, type ActivityType } from "@shared/crm";
import type { ActivityRow, DealCard } from "@shared/schema";
import { CalendarPlus, Check, Loader2, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { StageIcon } from "@/components/stage-icon";
import { dateInputValue, formatDateTime, relativeDay } from "@/lib/format";
import { ACTIVITY_META } from "@/lib/meta";
import { noteFor, type DealActions, type DealState, type NewActivity } from "./types";

function DoneBox({
  activity,
  busy,
  onToggle,
}: {
  activity: ActivityRow;
  busy: boolean;
  onToggle: (done: boolean) => void;
}) {
  if (busy) return <Loader2 className="text-muted-foreground size-3.5 shrink-0 animate-spin" />;
  return (
    <input
      type="checkbox"
      checked={activity.done}
      onChange={(event) => onToggle(event.target.checked)}
      aria-label={activity.done ? `Mark “${activity.subject}” not done` : `Mark “${activity.subject}” done`}
      className="accent-foreground size-3.5 shrink-0 cursor-pointer"
    />
  );
}

function Planned({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  const upcoming = card.activities.filter((a) => !a.done).toSorted((a, b) => a.dueAt.localeCompare(b.dueAt));
  return (
    <Section title="Next steps" meta={upcoming.length ? `${upcoming.length} planned` : undefined}>
      {upcoming.length === 0 ? (
        card.deal.status === "open" ? (
          <Callout tone="warning" icon={<TriangleAlert />}>
            No next step is planned. Schedule one so the deal doesn't stall.
          </Callout>
        ) : (
          <p className="text-subtle-foreground text-sm">Nothing planned.</p>
        )
      ) : (
        <ul className="bg-card overflow-hidden rounded-lg border">
          {upcoming.map((activity) => {
            const Icon = ACTIVITY_META[activity.type].icon;
            const note = noteFor(state, activity.id);
            return (
              <li key={activity.id} className="border-b last:border-b-0">
                <div className="flex min-h-9 items-center gap-2.5 px-3 py-1.5 text-[13px]">
                  <DoneBox
                    activity={activity}
                    busy={state.busy === activity.id}
                    onToggle={(done) => actions.onToggle(activity, done)}
                  />
                  <Icon
                    className="text-muted-foreground size-3.5 shrink-0"
                    aria-label={ACTIVITY_META[activity.type].label}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{activity.subject}</span>
                    {activity.note && (
                      <span className="text-muted-foreground block truncate text-xs">{activity.note}</span>
                    )}
                  </span>
                  <Chip
                    tone={activity.overdue ? "danger" : "neutral"}
                    className="tabular"
                    title={formatDateTime(activity.dueAt)}
                  >
                    {activity.overdue
                      ? `Overdue ${relativeDay(activity.dueAt, card.now).toLowerCase()}`
                      : relativeDay(activity.dueAt, card.now)}
                  </Chip>
                  <PersonAvatar person={activity.owner} />
                </div>
                {note && (
                  <p role="alert" className="text-danger border-t px-3 py-1.5 text-[11px]">
                    {note}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function ActivityForm({
  card,
  state,
  onSubmit,
}: {
  card: DealCard;
  state: DealState;
  onSubmit: (activity: NewActivity) => Promise<boolean>;
}) {
  const [type, setType] = useState<ActivityType>("call");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");
  const [date, setDate] = useState(() => dateInputValue(Date.parse(card.now) + 86_400_000));
  const [time, setTime] = useState("10:00");
  const [missing, setMissing] = useState<string | null>(null);
  const busy = state.busy === "log";

  const submit = async (done: boolean) => {
    const text = subject.trim();
    if (!text) {
      setMissing("Add a subject first");
      return;
    }
    if (!done && !date) {
      setMissing("Pick a date to schedule it");
      return;
    }
    setMissing(null);
    // "Log as done" records it as happening now; the date and time only schedule.
    const dueAt = done ? undefined : new Date(`${date}T${time || "09:00"}`).toISOString();
    if (await onSubmit({ type, subject: text, note: note.trim(), dueAt, done })) {
      setSubject("");
      setNote("");
    }
  };

  return (
    <form
      className="bg-card flex flex-col gap-2 rounded-lg border p-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        void submit(false);
      }}
    >
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Activity type">
        {ACTIVITY_TYPES.map((option) => {
          const Icon = ACTIVITY_META[option].icon;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={type === option}
              onClick={() => setType(option)}
              className="text-muted-foreground hover:bg-accent hover:text-foreground aria-checked:border-input aria-checked:bg-accent aria-checked:text-foreground inline-flex h-6 cursor-pointer items-center gap-1 rounded-md border px-2 text-xs transition-colors"
            >
              <Icon className="size-3.5" />
              {ACTIVITY_META[option].label}
            </button>
          );
        })}
      </div>
      <Input
        value={subject}
        onChange={(event) => setSubject(event.target.value)}
        placeholder={ACTIVITY_META[type].placeholder}
        aria-label="Subject"
        aria-invalid={missing === "Add a subject first" ? true : undefined}
        disabled={busy}
      />
      <Textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Notes (optional)"
        aria-label="Notes"
        className="min-h-12"
        disabled={busy}
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Input
          type="date"
          value={date}
          onChange={(event) => setDate(event.target.value)}
          aria-label="Due date"
          className="tabular h-7 w-[140px] text-xs"
        />
        <Input
          type="time"
          value={time}
          onChange={(event) => setTime(event.target.value)}
          aria-label="Due time"
          className="tabular h-7 w-[96px] text-xs"
        />
        <div className="ml-auto flex gap-1.5">
          <Button type="button" variant="outline" size="xs" disabled={busy} onClick={() => void submit(true)}>
            <Check />
            Log as done
          </Button>
          <Button type="submit" size="xs" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <CalendarPlus />}
            Schedule
          </Button>
        </div>
      </div>
      <FieldNote busy={busy} note={missing ?? noteFor(state, "log")} />
    </form>
  );
}

type Item =
  | { at: string; key: string; activity: ActivityRow; visit?: never }
  | { at: string; key: string; visit: DealCard["stageHistory"][number]; activity?: never };

function History({
  card,
  state,
  actions,
  children,
}: {
  card: DealCard;
  state: DealState;
  actions: DealActions;
  children: ReactNode;
}) {
  const stageById = new Map(card.stages.map((s) => [s.id, s]));
  const items: Item[] = [
    ...card.stageHistory.map((visit, i) => ({ at: visit.enteredAt, key: `visit-${i}`, visit })),
    ...card.activities
      .filter((a) => a.done)
      .map((activity) => ({ at: activity.doneAt ?? activity.dueAt, key: activity.id, activity })),
  ].toSorted((a, b) => a.at.localeCompare(b.at));
  const when = (at: string): ReactNode => <When at={at} label={timeAgo(at, card.now)} title={formatDateTime(at)} />;

  return (
    <Section title="Activity" className="gap-3">
      <Timeline>
        {items.map((item) => {
          if (item.visit) {
            const stage = stageById.get(item.visit.stageId);
            return (
              <TimelineEvent
                key={item.key}
                icon={stage ? <StageIcon stage={stage} className="mt-0.5 size-4" /> : undefined}
                when={when(item.at)}
              >
                {item.key === "visit-0" ? "Deal created in " : "Moved to "}
                <Strong>{item.visit.stageName}</Strong>
                {item.visit.leftAt && <span className="text-subtle-foreground tabular"> · {item.visit.days}d</span>}
              </TimelineEvent>
            );
          }
          const { activity } = item;
          const Icon = ACTIVITY_META[activity.type].icon;
          const note = noteFor(state, activity.id);
          return (
            <TimelineCard
              key={item.key}
              author={activity.owner}
              title={
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <span className="truncate">{activity.owner.name}</span>
                  <span className="text-muted-foreground inline-flex shrink-0 items-center gap-1 font-normal">
                    <Icon className="size-3" />
                    {ACTIVITY_META[activity.type].label.toLowerCase()}
                    {activity.contact ? ` with ${activity.contact.name}` : ""}
                  </span>
                </span>
              }
              when={when(item.at)}
              aside={
                <DoneBox
                  activity={activity}
                  busy={state.busy === activity.id}
                  onToggle={(done) => actions.onToggle(activity, done)}
                />
              }
            >
              <p className="text-sm font-medium">{activity.subject}</p>
              {activity.note && (
                <p className="text-muted-foreground mt-0.5 text-sm leading-relaxed whitespace-pre-line">
                  {activity.note}
                </p>
              )}
              <FieldNote note={note} />
            </TimelineCard>
          );
        })}
      </Timeline>
      {children}
    </Section>
  );
}

export function DealActivities({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  return (
    <>
      <Planned card={card} state={state} actions={actions} />
      <History card={card} state={state} actions={actions}>
        <ActivityForm card={card} state={state} onSubmit={actions.onLog} />
      </History>
    </>
  );
}
