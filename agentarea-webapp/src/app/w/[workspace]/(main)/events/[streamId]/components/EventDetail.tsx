import { getTranslations } from "next-intl/server";
import type { StreamEventResponse } from "@/api/client/types.gen";
import SectionLoadError from "@/components/SectionLoadError";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { getStreamEvent, listTriggers } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { optionalApiData } from "@/lib/server-resource";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import type { DispositionFilter } from "@/lib/streamOutcome";
import { eventRowId, feedHref } from "../feedHref";
import FocusOnMount from "./FocusOnMount";

const PANEL_ID = "event-detail";
const TITLE_ID = "event-detail-title";

type Translator = Awaited<ReturnType<typeof getTranslations>>;

export default async function EventDetail({
  streamId,
  sequence,
  outcome,
  before,
}: {
  streamId: string;
  sequence: number;
  outcome: DispositionFilter;
  before?: number;
}) {
  const [t, tFilter, eventResult, triggersResult] = await Promise.all([
    getTranslations("EventsPage.detail"),
    getTranslations("EventsPage.filter"),
    getStreamEvent(streamId, sequence),
    listTriggers(),
  ]);
  // Gone past retention, or never existed: the feed is still there, so only
  // this panel says so.
  const event = optionalApiData(eventResult, "stream event");
  const closeHref = `${feedHref(streamId, { outcome, before })}#${eventRowId(sequence)}`;

  return (
    <section
      id={PANEL_ID}
      aria-labelledby={TITLE_ID}
      tabIndex={-1}
      className="rounded-md border border-zinc-200 bg-white card-shadow outline-none dark:border-zinc-700 dark:bg-zinc-800 lg:sticky lg:top-0 lg:self-start"
    >
      <FocusOnMount key={sequence} targetId={PANEL_ID} />
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <h2 id={TITLE_ID} className="text-base font-semibold">
          {t("title", { sequence })}
        </h2>
        <WorkspaceLink href={closeHref} className="note hover:underline">
          {t("close")}
        </WorkspaceLink>
      </header>
      {event ? (
        <EventBody
          event={event}
          t={t}
          tFilter={tFilter}
          triggerNames={
            new Map(
              (triggersResult.data ?? []).map((trigger) => [
                trigger.id,
                trigger.name,
              ])
            )
          }
          triggersError={
            triggersResult.error || !triggersResult.data
              ? apiErrorMessage(triggersResult, t("triggersLoadFailed"))
              : null
          }
        />
      ) : (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("gone")}
        </div>
      )}
    </section>
  );
}

function EventBody({
  event,
  t,
  tFilter,
  triggerNames,
  triggersError,
}: {
  event: StreamEventResponse;
  t: Translator;
  tFilter: Translator;
  triggerNames: Map<string, string>;
  triggersError: string | null;
}) {
  return (
    <div className="space-y-4 p-4">
      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
          {t("subscribers")}
        </h3>
        {triggersError && <SectionLoadError message={triggersError} />}
        {event.outcomes.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {t("noOutcomes")}
          </div>
        ) : (
          <ul className="space-y-2">
            {event.outcomes.map((o) => {
              const presentation = getStreamOutcomeStatusPresentation(
                o.verdict
              );
              return (
                <li
                  key={o.subscription_id}
                  className="card-item space-y-1 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    {o.trigger_id ? (
                      <WorkspaceLink
                        href={`/triggers/${o.trigger_id}`}
                        className="truncate font-medium hover:underline"
                      >
                        {triggerNames.get(o.trigger_id) ?? t("trigger")}
                      </WorkspaceLink>
                    ) : (
                      <span className="font-medium">{t("forward")}</span>
                    )}
                    <StatusIndicator size="sm" kind={presentation.kind}>
                      {presentation.labelKey
                        ? tFilter(presentation.labelKey)
                        : presentation.label}
                      {presentation.labelKey === "unknown" && (
                        <span className="ml-1 font-mono text-xs">
                          {o.verdict}
                        </span>
                      )}
                    </StatusIndicator>
                  </div>
                  {o.reason && (
                    <p className="break-words text-sm text-muted-foreground">
                      {o.reason}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    {o.score != null && (
                      <span className="tabular-nums">
                        {t("score")}: {o.score.toFixed(2)}
                      </span>
                    )}
                    {o.task_id && (
                      <WorkspaceLink
                        href={`/tasks/${o.task_id}`}
                        className="text-primary hover:underline"
                      >
                        {t("task")}
                      </WorkspaceLink>
                    )}
                    {o.derived_sequences.length > 0 && (
                      <span className="tabular-nums">
                        {t("derived")}: {o.derived_sequences.join(", ")}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {event.causation_id && (
        <div className="text-xs text-muted-foreground">
          {t("causedBy")}:{" "}
          <span className="break-all font-mono">{event.causation_id}</span>
        </div>
      )}
      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
          {t("data")}
        </h3>
        <pre className="max-h-96 overflow-auto rounded-md bg-muted/50 p-3 text-xs">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      </div>
    </div>
  );
}
