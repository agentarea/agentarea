"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  fetchAuditLogs,
  type AuditEvent,
} from "@/app/w/[workspace]/(main)/settings/audit/actions";
import {
  AuditAction,
  AuditActor,
} from "@/app/w/[workspace]/(main)/settings/audit/AuditCells";
import { AuditChangeList } from "@/app/w/[workspace]/(main)/settings/audit/AuditChangeList";
import EmptyState from "@/components/EmptyState";
import { SectionCard } from "@/components/Overview/OverviewCard";
import { RowSkeleton } from "@/components/Overview/OverviewSkeleton";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";

// Audit trail scoped to a single MCP connection (the Activity tab). Read-only —
// surfaces the config-change history the audit store already records for this
// instance (mcp_instance.create / update / delete), so a reviewer can answer
// "who changed this connection, and when" without leaving the page.
export function InstanceActivitySection({
  instanceId,
}: {
  instanceId: string;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.activity");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    fetchAuditLogs({
      resource_type: "mcp_instance",
      resource_id: instanceId,
      limit: 20,
    }).then(({ data, error }) => {
      if (!active) return;
      if (error) {
        setUnavailable(true);
        setEvents([]);
        return;
      }
      setEvents(data?.events ?? []);
    });
    return () => {
      active = false;
    };
  }, [instanceId]);

  if (events === null) {
    return (
      <SectionCard>
        {Array.from({ length: 4 }).map((_, i) => (
          <RowSkeleton key={i} titleClassName="h-3 w-48" subClassName="w-24" />
        ))}
      </SectionCard>
    );
  }

  // Audit sink disabled or backend error: on its own tab, say so rather than
  // leave the page blank.
  if (unavailable) {
    return <EmptyState title={t("unavailable")} iconsType="audit" />;
  }

  if (events.length === 0) {
    return (
      <EmptyState
        title={t("empty")}
        description={t("emptyDescription")}
        iconsType="audit"
      />
    );
  }

  return (
    <SectionCard>
      <div>
        {events.map((event) => {
          const hasChanges = !!event.changes && event.changes.length > 0;
          const isExpanded = expandedId === event.id;
          return (
            <div
              key={event.id}
              className="border-t border-border/60 first:border-t-0"
            >
              <button
                type="button"
                className="flex w-full items-center gap-3 px-[15px] py-[11px] text-left text-[12.5px] hover:bg-muted/40"
                onClick={() =>
                  hasChanges && setExpandedId(isExpanded ? null : event.id)
                }
              >
                <span className="w-4 shrink-0 text-muted-foreground">
                  {hasChanges ? (
                    isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )
                  ) : null}
                </span>
                <span className="w-44 shrink-0">
                  <AuditAction action={event.action} />
                </span>
                <span className="min-w-0 flex-1">
                  <AuditActor event={event} />
                </span>
                {event.source_ip && (
                  <span className="hidden shrink-0 font-mono text-xs text-muted-foreground sm:inline">
                    {event.source_ip}
                  </span>
                )}
                <span className="shrink-0">
                  <TableDateDisplay
                    dateString={event.created_at}
                    oneRow
                    relative
                  />
                </span>
              </button>
              {isExpanded && hasChanges && (
                <AuditChangeList
                  changes={event.changes}
                  className="space-y-1 border-t border-border/60 bg-muted/20 px-[15px] py-2 pl-11"
                />
              )}
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}
