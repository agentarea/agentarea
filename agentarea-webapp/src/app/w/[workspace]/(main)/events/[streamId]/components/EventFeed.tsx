import { getLocale, getTranslations } from "next-intl/server";
import type { StreamEventResponse } from "@/api/client/types.gen";
import Table from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { listStreamEvents } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import {
  eventDisposition,
  matchesDisposition,
  summarizeOutcomes,
  type DispositionFilter,
} from "@/lib/streamOutcome";
import { formatDateTime } from "@/utils/dateUtils";
import { eventRowId, feedHref } from "../feedHref";

const PAGE = 50;

/** `Table` keys rows by `id`; an event is identified by its sequence. */
type FeedRow = StreamEventResponse & { id: number };

export default async function EventFeed({
  streamId,
  outcome,
  before,
  selected,
}: {
  streamId: string;
  outcome: DispositionFilter;
  before?: number;
  selected?: number;
}) {
  const [t, tFilter, locale, pageResult] = await Promise.all([
    getTranslations("EventsPage.feed"),
    getTranslations("EventsPage.filter"),
    getLocale(),
    listStreamEvents(streamId, { before, limit: PAGE }),
  ]);
  const page = requireApiData(pageResult, "stream events");

  if (page.events.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        {t("empty")}
      </div>
    );
  }

  const rows: FeedRow[] = page.events
    .filter((e) => matchesDisposition(e.outcomes, outcome))
    .map((e) => ({ ...e, id: e.sequence }));

  return (
    <div className="space-y-3">
      {rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("noneMatching")}
        </div>
      ) : (
        <Table<FeedRow>
          data={rows}
          rowHref={(e) =>
            feedHref(streamId, { outcome, before, event: e.sequence })
          }
          rowProps={(e) => ({
            id: eventRowId(e.sequence),
            ...(e.sequence === selected
              ? { "aria-current": "true", className: "bg-muted/40" }
              : {}),
          })}
          columns={[
            {
              header: t("received"),
              accessor: "received_at",
              rowLink: true,
              cellClassName: "whitespace-nowrap tabular-nums",
              render: (value) => formatDateTime(String(value), locale),
            },
            { header: t("kind"), accessor: "kind" },
            {
              header: t("key"),
              accessor: "event_key",
              cellClassName: "max-w-[260px] truncate font-mono text-xs",
            },
            {
              header: t("outcome"),
              accessor: "outcomes",
              render: (_value, e) => {
                const summary = summarizeOutcomes(e?.outcomes ?? []);
                const presentation = getStreamOutcomeStatusPresentation(
                  eventDisposition(summary)
                );
                return (
                  <StatusIndicator size="sm" kind={presentation.kind}>
                    {presentation.labelKey
                      ? tFilter(presentation.labelKey)
                      : presentation.label}
                    {summary.total > 1 && (
                      <span className="ml-1 tabular-nums text-muted-foreground">
                        {summary.reacted}/{summary.total}
                      </span>
                    )}
                  </StatusIndicator>
                );
              },
            },
          ]}
        />
      )}
      {page.next_before != null && (
        <WorkspaceLink
          href={feedHref(streamId, { outcome, before: page.next_before })}
          className="text-sm text-primary hover:underline"
        >
          {t("older")}
        </WorkspaceLink>
      )}
    </div>
  );
}
