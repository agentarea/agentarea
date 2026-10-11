"use client";

import { useFormatter, useNow, useTranslations } from "next-intl";
import type { ToolCallApprovalResponse } from "@/api/client/types.gen";
import { formatRelative } from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";

/**
 * Client tool calls waiting on an approval link. Each row opens the same
 * approve page the link in the chat points at.
 */
export function InboxToolCallList({
  approvals,
}: {
  approvals: ToolCallApprovalResponse[];
}) {
  const t = useTranslations("InboxPage.toolCalls");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const router = useWorkspaceRouter();

  return (
    <section aria-label={t("title")}>
      <h2 className="border-b border-zinc-200 px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground dark:border-zinc-700">
        {t("title")}
      </h2>
      {approvals.map((approval) => (
        <InteractiveListRow
          key={approval.id}
          onClick={() => router.push(`/approve/${approval.id}`)}
          contentClassName="gap-3"
          start={
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground">
              <EntityIcon kind="tool" />
            </span>
          }
          endClassName="flex-col items-end gap-1"
          end={
            <>
              <StatusIndicator kind="attention" aria-label={t("waiting")} />
              <span className="whitespace-nowrap text-[11.5px] text-muted-foreground">
                {formatRelative(format, now, approval.created_at)}
              </span>
            </>
          }
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-foreground">
              {t("row", { tool: approval.tool, connector: approval.connector })}
            </p>
            <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
              {approval.client_name
                ? t("via", { client: approval.client_name })
                : t("viaMcp")}
            </p>
          </div>
        </InteractiveListRow>
      ))}
    </section>
  );
}
