"use client";

import type { MouseEvent } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Activity, Clock, Pencil } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerStatusPresentation } from "@/lib/status";
import {
  describeTriggerSchedule,
  findTriggerCatalogEntry,
  formatCompactDistance,
  getTriggerColor,
  getTriggerDisplayName,
  getTriggerHealth,
  getTriggerIconComponent,
  TriggerTile,
  type EnrichedTrigger,
  type TriggerCatalogEntry,
} from "./triggerDisplay";

interface TriggersTableProps {
  triggers: EnrichedTrigger[];
  catalog?: TriggerCatalogEntry[];
  hideChannelColumn?: boolean;
}

export default function TriggersTable({
  triggers,
  catalog = [],
  hideChannelColumn = false,
}: TriggersTableProps) {
  const tStatus = useTranslations("TriggersPage.status");
  const router = useRouter();

  const stop = (event: MouseEvent) => event.stopPropagation();

  return (
    <div>
      {triggers.map((trigger) => {
        const entry = findTriggerCatalogEntry(trigger, catalog);
        const Icon = getTriggerIconComponent(entry, trigger);
        const color = getTriggerColor(entry, trigger);
        const typeLabel = getTriggerDisplayName(trigger, entry);
        const schedule = describeTriggerSchedule(trigger);
        const health = getTriggerHealth(trigger);
        const status = getTriggerStatusPresentation(health);
        const nextRun = trigger.next_run_time ?? trigger.next_run_at;

        return (
          <InteractiveListRow
            key={trigger.id}
            onClick={() => router.push(`/triggers/${trigger.id}`)}
            start={<TriggerTile color={color} icon={Icon} variant="row" />}
            contentClassName="gap-3"
            endClassName="gap-4"
            end={
              <>
                {!hideChannelColumn && (
                  <span className="flex w-auto shrink-0 justify-start sm:w-[112px]">
                    <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80">
                      <span
                        className="h-[7px] w-[7px] rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      {typeLabel}
                    </span>
                  </span>
                )}

                <span className="hidden w-[180px] shrink-0 items-center gap-1.5 md:flex">
                  {trigger.agent_name && (
                    <AgentAvatar
                      agent={{
                        id: trigger.agent_id || trigger.agent_name,
                        name: trigger.agent_name,
                      }}
                      size="xs"
                    />
                  )}
                  <span className="truncate text-[11.5px] text-muted-foreground">
                    {trigger.agent_name || "—"}
                  </span>
                </span>

                <span className="hidden w-14 shrink-0 items-center justify-end gap-1 text-[11.5px] text-muted-foreground/80 lg:flex">
                  {nextRun ? (
                    <>
                      <Clock className="h-3 w-3" strokeWidth={1.7} />
                      {formatCompactDistance(nextRun)}
                    </>
                  ) : (
                    <span className="text-muted-foreground/60">—</span>
                  )}
                </span>

                <span className="hidden w-[116px] shrink-0 items-center justify-start sm:flex">
                  <StatusIndicator
                    size="sm"
                    tone={status.tone}
                    pulse={status.pulse}
                  >
                    {tStatus(health)}
                  </StatusIndicator>
                </span>
              </>
            }
            hoverActionsClassName="bg-gradient-to-l from-muted/60 via-muted/60 to-transparent dark:from-zinc-800/50 dark:via-zinc-800/50"
            hoverActions={
              <>
                <button
                  type="button"
                  title="Executions"
                  onClick={(event) => {
                    stop(event);
                    router.push(`/triggers/${trigger.id}/executions`);
                  }}
                  className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
                >
                  <Activity className="h-[15px] w-[15px]" />
                </button>
                <button
                  type="button"
                  title="Edit"
                  onClick={(event) => {
                    stop(event);
                    router.push(`/triggers/${trigger.id}/edit`);
                  }}
                  className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
                >
                  <Pencil className="h-[15px] w-[15px]" />
                </button>
              </>
            }
          >
            <>
              <span className="min-w-0 max-w-[280px] shrink truncate text-[13px] font-medium text-foreground">
                {trigger.name}
              </span>
              <span className="hidden min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground sm:block">
                {schedule}
              </span>
            </>
          </InteractiveListRow>
        );
      })}
    </div>
  );
}
