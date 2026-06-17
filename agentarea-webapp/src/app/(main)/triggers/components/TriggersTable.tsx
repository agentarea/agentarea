"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Clock, Webhook } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  describeTriggerSchedule,
  formatCompactDistance,
  getTriggerHealth,
  type TriggerHealth,
} from "./triggerDisplay";

interface TriggersTableProps {
  triggers: any[];
  /** Accepted for call-site compatibility; the row now derives everything it
   *  needs from the trigger itself. */
  catalog?: any[];
}

const STATUS_STYLES: Record<TriggerHealth, { dot: string; text: string }> = {
  active: {
    dot: "bg-emerald-500",
    text: "text-emerald-600 dark:text-emerald-500",
  },
  paused: {
    dot: "bg-zinc-300 dark:bg-zinc-600",
    text: "text-muted-foreground",
  },
  error: {
    dot: "bg-red-500",
    text: "text-red-600 dark:text-red-500",
  },
};

export default function TriggersTable({ triggers }: TriggersTableProps) {
  const tStatus = useTranslations("TriggersPage.status");
  const tType = useTranslations("TriggersPage.type");

  return (
    <div className="-mx-4 -mt-5 border-t border-zinc-100 dark:border-zinc-800">
      {triggers.map((trigger) => {
        const isCron = trigger.trigger_type === "cron";
        const TypeIcon = isCron ? Clock : Webhook;
        const schedule = describeTriggerSchedule(trigger);
        const health = getTriggerHealth(trigger);
        const status = STATUS_STYLES[health];
        const nextRun = trigger.next_run_time ?? trigger.next_run_at;
        const agentName = trigger.agent_name || "—";

        return (
          <Link
            key={trigger.id}
            href={`/triggers/${trigger.id}`}
            className="group flex items-center gap-3 border-b border-zinc-100 px-4 py-2.5 transition-colors hover:bg-primary/5 dark:border-zinc-800 dark:hover:bg-primary/10"
          >
            {/* Trigger icon */}
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                isCron
                  ? "bg-primary/10 text-primary"
                  : "bg-violet-100 text-violet-600 dark:bg-violet-950/40 dark:text-violet-400"
              )}
            >
              <TypeIcon className="h-3.5 w-3.5" />
            </span>

            {/* Name */}
            <span className="min-w-0 flex-[1.7] truncate text-[13px] font-medium text-foreground group-hover:text-primary">
              {trigger.name}
            </span>

            {/* Schedule description */}
            <span className="hidden min-w-0 flex-[1.4] truncate text-[13px] text-muted-foreground md:block">
              {schedule}
            </span>

            {/* Trigger type badge */}
            <span className="hidden shrink-0 sm:flex">
              <Badge
                variant="outline"
                className="h-5 gap-1 px-1.5 font-normal text-foreground"
              >
                <TypeIcon
                  className={cn(
                    "h-3 w-3",
                    isCron ? "text-primary" : "text-violet-500"
                  )}
                />
                {isCron ? tType("cron") : tType("webhook")}
              </Badge>
            </span>

            {/* Agent */}
            <span className="hidden min-w-0 flex-[1.2] items-center gap-2 md:flex">
              {trigger.agent_name && (
                <AgentAvatar
                  agent={{ id: trigger.agent_id || trigger.agent_name, name: trigger.agent_name }}
                  size="xs"
                />
              )}
              <span className="truncate text-[13px] text-muted-foreground">
                {agentName}
              </span>
            </span>

            {/* Next run */}
            <span className="hidden w-[72px] shrink-0 items-center justify-end gap-1 text-[13px] text-muted-foreground lg:flex">
              {nextRun ? (
                <>
                  <Clock className="h-3 w-3" />
                  {formatCompactDistance(nextRun)}
                </>
              ) : (
                <span className="text-muted-foreground/60">—</span>
              )}
            </span>

            {/* Status */}
            <span className="flex w-[92px] shrink-0 items-center justify-end gap-1.5">
              <span className={cn("h-1.5 w-1.5 rounded-full", status.dot)} />
              <span className={cn("text-[13px] font-medium", status.text)}>
                {tStatus(health)}
              </span>
            </span>
          </Link>
        );
      })}
    </div>
  );
}
