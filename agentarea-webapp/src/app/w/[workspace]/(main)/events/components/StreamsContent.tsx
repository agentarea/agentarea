import { getLocale, getTranslations } from "next-intl/server";
import type { StreamResponse } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { listStreams } from "@/lib/api";
import { EntityIcon } from "@/lib/entity-icons";
import { requireApiData } from "@/lib/server-resource";
import { formatDate } from "@/utils/dateUtils";

export default async function StreamsContent({
  search,
  viewMode,
}: {
  search: string;
  viewMode: string;
}) {
  const [t, tCommon, tTriggers, locale, streamsResult] = await Promise.all([
    getTranslations("EventsPage"),
    getTranslations("Common"),
    getTranslations("TriggersPage"),
    getLocale(),
    listStreams(),
  ]);
  const streams = requireApiData(streamsResult, "streams");
  const query = search.trim().toLowerCase();
  const shown = query
    ? streams.filter(
        (s) =>
          s.name.toLowerCase().includes(query) ||
          s.description.toLowerCase().includes(query)
      )
    : streams;

  if (streams.length === 0) {
    return (
      <EmptyState
        title={t("noStreams")}
        description={t("noStreamsDescription")}
        iconsType="triggers"
        action={{ label: tTriggers("createTrigger"), href: "/triggers/create" }}
      />
    );
  }

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={shown}
      itemLink={(stream: StreamResponse) => `/events/${stream.id}`}
      emptyState={
        <EmptyState
          title={t("noMatchingStreams")}
          iconsType="triggers"
          action={{ label: tCommon("clearSearch"), href: "/events" }}
        />
      }
      columns={[
        {
          header: t("streams.name"),
          accessor: "name",
          rowLink: true,
          render: (name: unknown, stream?: StreamResponse) => (
            <div className="flex items-center gap-2">
              <EntityIcon kind="stream" className="text-primary" />
              <div>
                <div className="font-medium">{String(name)}</div>
                {stream?.description && (
                  <div className="mt-1 line-clamp-1 max-w-md text-xs text-muted-foreground">
                    {stream.description}
                  </div>
                )}
              </div>
            </div>
          ),
        },
        {
          header: t("streams.retention"),
          accessor: "retention_days",
          cellClassName: "tabular-nums",
          render: (days: unknown) =>
            t("streams.retentionDays", { count: Number(days) }),
        },
        {
          header: t("streams.created"),
          accessor: "created_at",
          render: (value: unknown) => formatDate(String(value), locale),
        },
      ]}
      cardContent={(stream: StreamResponse) => (
        <div className="flex h-full flex-col gap-2">
          <div className="flex items-center gap-2">
            <EntityIcon kind="stream" className="text-primary" />
            <div className="truncate text-[16px] font-[500]">{stream.name}</div>
          </div>
          {stream.description && (
            <div className="line-clamp-2 text-[14px] opacity-50">
              {stream.description}
            </div>
          )}
          <div className="mt-auto text-xs tabular-nums text-muted-foreground">
            {t("streams.retentionDays", { count: stream.retention_days })}
          </div>
        </div>
      )}
    />
  );
}
