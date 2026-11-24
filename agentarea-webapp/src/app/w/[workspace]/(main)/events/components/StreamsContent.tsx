import { getTranslations } from "next-intl/server";
import type { StreamResponse } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { listStreams } from "@/lib/api";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import StreamCard, { StreamAvatar } from "./StreamCard";

export default async function StreamsContent({
  search,
  viewMode,
}: {
  search: string;
  viewMode: string;
}) {
  const [t, tCommon, tTriggers, streamsResult] = await Promise.all([
    getTranslations("EventsPage"),
    getTranslations("Common"),
    getTranslations("TriggersPage"),
    listStreams(),
  ]);
  // The platform's stream is named and described by the platform.
  const streams = requireApiData(streamsResult, "streams").map((stream) =>
    isPlatformStream(stream)
      ? {
          ...stream,
          name: t("streams.platformName"),
          description: t("streams.platformDescription"),
        }
      : stream
  );
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

  // As the Projects table: a tile, the name and a line of description, then
  // the plain columns in the table's muted 13px.
  const columns = [
    {
      header: t("streams.name"),
      accessor: "name",
      rowLink: true,
      render: (name: unknown, stream?: StreamResponse) =>
        stream && (
          <div className="flex min-w-0 items-center gap-2.5">
            <StreamAvatar stream={stream} size={28} />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-foreground">
                {String(name)}
              </div>
              {stream.description && (
                <div className="max-w-md truncate text-xs text-muted-foreground">
                  {stream.description}
                </div>
              )}
            </div>
          </div>
        ),
    },
    {
      header: t("streams.writtenBy"),
      accessor: "kind",
      headerClassName: "hidden w-[200px] md:table-cell",
      cellClassName: "hidden md:table-cell",
      render: (_value: unknown, stream?: StreamResponse) => (
        <span className="text-[13px] text-muted-foreground">
          {stream && isPlatformStream(stream)
            ? t("streams.platformWriter")
            : t("streams.sourcesWriter")}
        </span>
      ),
    },
    {
      header: t("streams.created"),
      accessor: "created_at",
      headerClassName: "w-[120px]",
      // As the tables elsewhere (Tasks): the shared date cell, the day only,
      // how long ago for the last five days.
      render: (value: unknown) => (
        <TableDateDisplay
          dateString={String(value)}
          onlyDate
          relative
          relativeDays={5}
        />
      ),
    },
  ];

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={shown}
      columns={columns}
      itemLink={(stream: StreamResponse) => `/events/${stream.id}`}
      // StreamCard is a LinkedCard: it owns its surface and its link.
      wrapCardContent={false}
      cardContent={(stream: StreamResponse) => <StreamCard stream={stream} />}
      emptyState={
        <EmptyState
          title={t("noMatchingStreams")}
          iconsType="triggers"
          action={{ label: tCommon("clearSearch"), href: "/events/streams" }}
        />
      }
    />
  );
}
