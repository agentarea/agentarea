"use client";

import { useTranslations } from "next-intl";
import type { Processing } from "@/api/client/types.gen";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { processingProgress, shortAge } from "@/lib/eventFeed";
import { getEventProcessingStatusPresentation } from "@/lib/status";
import { parseUtcTimestamp } from "@/utils/dateUtils";

/**
 * What the platform did with one event: queued with its wait, how many
 * subscribers reacted of how many matched, and what they did.
 */
export default function ProcessingPill({
  processing,
  receivedAt,
  now,
}: {
  processing: Processing;
  receivedAt: string;
  /** The viewer's clock; null before the page knows it (server render). */
  now: number | null;
}) {
  const t = useTranslations("EventsPage");
  const presentation = getEventProcessingStatusPresentation(processing.status);
  const progress = processingProgress(processing);
  const received = parseUtcTimestamp(receivedAt)?.getTime() ?? null;

  let label: string;
  const details: string[] = [];
  switch (processing.status) {
    case "queued":
      label =
        now !== null && received !== null
          ? t("list.queuedFor", { age: shortAge(now - received) })
          : t("result.queued");
      break;
    case "processing":
      label = `${progress.done}/${progress.total}`;
      break;
    case "handled":
      label = `${progress.done}/${progress.total}`;
      if (progress.tasks)
        details.push(t("list.tasks", { count: progress.tasks }));
      if (progress.skipped)
        details.push(t("list.skipped", { count: progress.skipped }));
      break;
    case "error":
      label = `${progress.done}/${progress.total} · ${t("list.errors", { count: progress.errors })}`;
      break;
    case "skipped":
      label = t("list.skippedOf", {
        done: progress.done,
        total: progress.total,
      });
      break;
    case "no_handlers":
      label = t("result.no_handlers");
      break;
    default:
      label = t(`result.${presentation.labelKey ?? "unknown"}`);
  }

  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <StatusIndicator
        size="sm"
        kind={presentation.kind}
        className="shrink-0 tabular-nums"
        title={t(`result.${presentation.labelKey ?? "unknown"}`)}
      >
        {label}
      </StatusIndicator>
      {details.length > 0 && (
        <span className="truncate text-[11px] text-muted-foreground">
          {details.join(", ")}
        </span>
      )}
    </span>
  );
}
