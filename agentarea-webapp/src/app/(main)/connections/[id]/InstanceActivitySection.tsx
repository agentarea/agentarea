"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  fetchAuditLogs,
  type AuditEvent,
} from "@/app/(main)/settings/audit/actions";
import {
  auditActionColor,
  formatAuditTime,
} from "@/app/(main)/settings/audit/format";

// Audit trail scoped to a single MCP connection. Read-only — surfaces the
// config-change history the audit store already records for this instance
// (mcp_instance.create / update / delete), so a reviewer can answer
// "who changed this connection, and when" without leaving the page.
export function InstanceActivitySection({ instanceId }: { instanceId: string }) {
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
      <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
        {t("loading")}
      </div>
    );
  }

  // Audit sink disabled or backend error — stay quiet rather than clutter the
  // builder's happy path with an error card.
  if (unavailable) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <ScrollText className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium">
          {t("title", { count: events.length })}
        </h3>
      </div>

      {events.length === 0 ? (
        <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
          {t("empty")}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          {events.map((event) => {
            const hasChanges = !!event.changes && event.changes.length > 0;
            const isExpanded = expandedId === event.id;
            return (
              <div key={event.id} className="border-t first:border-t-0">
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40"
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
                  <Badge
                    variant="secondary"
                    className={`shrink-0 font-mono text-xs ${auditActionColor(event.action)}`}
                  >
                    {event.action}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {event.actor?.href ? (
                      <Link
                        href={event.actor.href}
                        className="font-medium hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {event.actor.label}
                      </Link>
                    ) : (
                      <span className="font-medium">
                        {event.actor?.label ?? event.actor_id}
                      </span>
                    )}
                  </span>
                  {event.source_ip && (
                    <span className="hidden shrink-0 font-mono text-xs text-muted-foreground sm:inline">
                      {event.source_ip}
                    </span>
                  )}
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatAuditTime(event.created_at)}
                  </span>
                </button>
                {isExpanded && hasChanges && (
                  <div className="space-y-1 border-t bg-muted/20 px-3 py-2 pl-10">
                    {event.changes?.map((change, i) => (
                      <div key={i} className="font-mono text-xs">
                        <span className="text-muted-foreground">
                          {String(change.field ?? "unknown")}:
                        </span>{" "}
                        <span className="text-red-500 line-through">
                          {String(change.before ?? "null")}
                        </span>{" "}
                        <span className="text-emerald-600">
                          {String(change.after ?? "null")}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
