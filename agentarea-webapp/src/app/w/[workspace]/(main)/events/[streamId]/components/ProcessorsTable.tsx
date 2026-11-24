"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";
import type { SubscriptionResponse } from "@/api/client/types.gen";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import WorkspaceLink from "@/components/WorkspaceLink";
import { EntityIcon } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";

/**
 * The code agents wrote to turn this stream's events into other streams'
 * events, read-only: where each writes, what it takes, when it was added;
 * a row opens its code beneath it.
 */
export default function ProcessorsTable({
  processors,
  streamNames,
}: {
  processors: SubscriptionResponse[];
  streamNames: Record<string, string>;
}) {
  const t = useTranslations("EventsPage");
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Table<SubscriptionResponse>
      className="table-fixed"
      data={processors}
      onRowClick={(processor) =>
        processor.code &&
        setOpen((current) => (current === processor.id ? null : processor.id))
      }
      isExpanded={(processor) => processor.id === open}
      // As the tools table opens a row: a small label over what the row
      // cannot show, on the table's own band. Plain text, not the highlighted
      // file preview: that one colours itself after it mounts, growing while
      // the row opens, and the opening jumps.
      renderExpanded={(processor) =>
        processor.code && (
          <section className="space-y-1.5 py-1">
            <div className="text-[11px] text-muted-foreground">
              {t("processors.code")}
            </div>
            <pre className="max-h-80 overflow-auto rounded-md border border-border bg-background px-3 py-2.5 font-mono text-[12px] leading-relaxed">
              {processor.code}
            </pre>
          </section>
        )
      }
      columns={[
        {
          header: t("processors.writesTo"),
          accessor: "output_stream_ids",
          render: (_value, processor) =>
            processor && (
              <span className="flex min-w-0 items-center gap-2">
                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  {processor.output_stream_ids.map((id) => (
                    <WorkspaceLink
                      key={id}
                      href={`/events/${id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1.5 text-[13px] font-medium text-foreground hover:text-primary"
                    >
                      <EntityIcon
                        kind="stream"
                        className="h-3.5 w-3.5 text-muted-foreground"
                      />
                      {streamNames[id] ?? id}
                    </WorkspaceLink>
                  ))}
                </span>
              </span>
            ),
        },
        {
          header: t("streamPage.takes"),
          accessor: "filter",
          headerClassName: "w-[260px]",
          cellClassName: "w-[260px]",
          render: (_value, processor) => {
            const kinds = Array.isArray(processor?.filter.kinds)
              ? (processor.filter.kinds as string[])
              : [];
            return (
              <span
                className={cn(
                  "block truncate text-[13px] text-muted-foreground",
                  kinds.length > 0 && "font-mono text-[12px]"
                )}
              >
                {kinds.length > 0
                  ? kinds.join(", ")
                  : t("processors.everyEvent")}
              </span>
            );
          },
        },
        {
          header: t("streams.created"),
          accessor: "created_at",
          headerClassName: "w-[140px]",
          cellClassName: "w-[140px]",
          render: (value) => (
            <TableDateDisplay
              dateString={String(value)}
              onlyDate
              relative
              relativeDays={5}
            />
          ),
        },
        // The row's own toggle, at its end as in the tools table.
        {
          header: "",
          accessor: "code",
          headerClassName: "w-[44px]",
          cellClassName: "w-[44px]",
          render: (_value, processor) =>
            processor?.code ? (
              <ChevronRight
                aria-hidden="true"
                className={cn(
                  "h-3.5 w-3.5 text-muted-foreground transition-transform",
                  processor.id === open && "rotate-90"
                )}
              />
            ) : null,
        },
      ]}
    />
  );
}
