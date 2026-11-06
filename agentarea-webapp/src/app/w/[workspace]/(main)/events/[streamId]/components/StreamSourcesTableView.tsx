"use client";

import { useTranslations } from "next-intl";
import type { StreamSourceResponse } from "@/api/client/types.gen";
import DeleteButton from "@/components/DeleteButton";
import EmptyState from "@/components/EmptyState";
import SourceTypeMark from "@/components/SourceTypeMark";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { CopyableText } from "@/components/ui/copyable-text";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { ApiResultLike } from "@/lib/api-errors";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";

/**
 * Where the stream's events come from, as the tables elsewhere: the source's
 * tile and name, how its events arrive, the URL a sender posts to, its
 * state, and delete.
 */
export default function StreamSourcesTableView({
  sources,
  types,
  onDelete,
}: {
  sources: StreamSourceResponse[];
  types: SourceType[];
  onDelete: (sourceId: string) => Promise<ApiResultLike>;
}) {
  const t = useTranslations("EventsPage");

  if (sources.length === 0) {
    return (
      <EmptyState
        title={t("streamPage.noSources")}
        description={t("sources.empty")}
        iconsType="triggers"
      />
    );
  }

  const nameOf = (source: StreamSourceResponse) =>
    sourceTypeBySlug(types, source.source_type)?.name ??
    source.source_type ??
    source.kind;

  return (
    <Table<StreamSourceResponse>
      className="table-fixed"
      data={sources}
      columns={[
        {
          header: t("streamPage.source"),
          accessor: "source_type",
          render: (_value, source) =>
            source && (
              <span className="flex min-w-0 items-center gap-2.5">
                <SourceTypeMark
                  type={sourceTypeBySlug(types, source.source_type)}
                  slug={source.source_type}
                  size={28}
                />
                <span className="truncate text-[13px] font-medium text-foreground">
                  {nameOf(source)}
                </span>
              </span>
            ),
        },
        {
          header: t("streamPage.delivery"),
          accessor: "kind",
          headerClassName: "hidden w-[140px] md:table-cell",
          cellClassName: "hidden w-[140px] md:table-cell",
          render: (value) => (
            <span className="text-[13px] text-muted-foreground">
              {t(`streamPage.deliveries.${String(value)}`)}
            </span>
          ),
        },
        {
          header: t("streamPage.address"),
          accessor: "webhook_url",
          headerClassName: "hidden w-[340px] lg:table-cell",
          cellClassName: "hidden w-[340px] lg:table-cell",
          render: (value) =>
            value ? (
              <CopyableText text={String(value)} className="max-w-full" />
            ) : (
              <span className="text-[13px] text-muted-foreground">—</span>
            ),
        },
        {
          header: t("streamPage.state"),
          accessor: "polled_at",
          headerClassName: "w-[200px]",
          cellClassName: "w-[200px]",
          render: (_value, source) => {
            if (!source) return null;
            if (source.poll_error) {
              return (
                <StatusIndicator
                  size="sm"
                  kind="failed"
                  title={source.poll_error}
                >
                  {t("streamPage.pollFailed")}
                </StatusIndicator>
              );
            }
            if (source.kind === "poll") {
              return source.polled_at ? (
                <TableDateDisplay
                  dateString={source.polled_at}
                  relative
                  relativeDays={5}
                  oneRow
                />
              ) : (
                <StatusIndicator size="sm" kind="queued">
                  {t("sources.notPolledYet")}
                </StatusIndicator>
              );
            }
            return (
              <StatusIndicator size="sm" kind="active">
                {t("streamPage.receiving")}
              </StatusIndicator>
            );
          },
        },
        {
          header: "",
          accessor: "id",
          headerClassName: "w-[110px]",
          cellClassName: "w-[110px] text-right",
          render: (_value, source) =>
            source && (
              <DeleteButton
                itemId={source.id}
                itemName={nameOf(source)}
                onDelete={onDelete}
                title={t("sources.deleteTitle")}
                description={t("sources.deleteDescription", {
                  name: nameOf(source),
                })}
                rowAction
              />
            ),
        },
      ]}
    />
  );
}
