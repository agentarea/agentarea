"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import { TaskCreator } from "@/components/TaskCreator";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { TriggerCatalogEntry } from "@/app/(main)/triggers/components/triggerDisplay";
import { getTaskSource } from "@/lib/taskSource";

interface TaskSourceBadgeProps {
  parameters?: Record<string, unknown> | null;
  /** tasks.created_by — the principal the task belongs to. */
  createdBy?: string | null;
  /**
   * Principal id -> display name, resolved by the caller via GET /v1/principals.
   * Covers both the task's own creator and any principal the source names (the
   * delegating agent). An id missing from the map is one nothing could resolve.
   */
  principalNames?: Record<string, string>;
  /** Names and draws the channel. Which channels exist is its business, not ours. */
  catalog?: TriggerCatalogEntry[];
  size?: "default" | "sm";
  className?: string;
}

export function TaskSourceBadge({
  parameters,
  createdBy,
  principalNames = {},
  catalog = [],
  size = "sm",
  className,
}: TaskSourceBadgeProps) {
  const t = useTranslations("TasksPage");
  const source = getTaskSource(parameters ?? undefined);
  const createdByName = createdBy ? principalNames[createdBy] : undefined;

  // "Manual" only ever meant "nothing automated matched", which is a fact about
  // the absence of a trigger rather than about the task. The person who started
  // it is the useful answer, so they take the chip's place outright.
  if (source.kind === "manual") {
    return <TaskCreator userId={createdBy} name={createdByName} />;
  }

  // A source may name a principal of its own — the agent that delegated. It
  // stays a name we looked up, never the id: an unresolved one simply goes
  // unmentioned.
  const detail =
    source.detail ??
    (source.principalId ? principalNames[source.principalId] : undefined);

  const entry = source.channel
    ? catalog.find(
        (item) =>
          item.webhook_type === source.channel || item.id === source.channel
      )
    : undefined;
  // One tone for every source. A per-source palette cannot survive an open set
  // — there is no colour to hand a channel that did not exist when this shipped
  // — and it never encoded anything anyway.
  const label = entry?.name ?? source.label;

  const badge = (
    <Badge variant="zinc" size={size} className={className}>
      {entry?.icon_url && (
        <Image
          src={entry.icon_url}
          alt=""
          aria-hidden
          width={12}
          height={12}
          className="h-3 w-3 shrink-0"
        />
      )}
      {/* The chip answers "where from". The specific instance — a trigger's
          name, a chat title — is a different question, and trigger names are
          sentences of their own ("PR opened → SEO review"), so they live in
          the tooltip. */}
      <span className="truncate max-w-[140px]">{label}</span>
    </Badge>
  );

  if (!detail && !createdByName) {
    return badge;
  }

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">{badge}</span>
        </TooltipTrigger>
        <TooltipContent>
          <div>
            <span className="font-medium">{label}</span>
            {detail && <span className="opacity-70"> · {detail}</span>}
          </div>
          {/* An automated task still has an owner — the person whose trigger or
              channel it is. There is no column left to put them in, so the
              tooltip carries them rather than dropping the fact. */}
          {createdByName && (
            <div className="opacity-70">
              {t("startedBy")}: {createdByName}
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
