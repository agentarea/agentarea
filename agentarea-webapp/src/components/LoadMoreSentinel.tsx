"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useOnVisible } from "@/hooks/use-on-visible";

interface LoadMoreSentinelProps {
  /** Another page follows; nothing renders once the list is complete. */
  hasMore: boolean;
  pending: boolean;
  /** Why the last page failed to load; set, it waits for a retry. */
  error: string | null;
  onLoadMore: () => void;
}

/**
 * The end of an infinite list: the next page loads as it scrolls into view.
 * After a failure it waits for a retry instead of asking again on every scroll.
 */
export default function LoadMoreSentinel({
  hasMore,
  pending,
  error,
  onLoadMore,
}: LoadMoreSentinelProps) {
  const t = useTranslations("Common");
  const ref = useOnVisible(onLoadMore, {
    enabled: hasMore && !pending && !error,
  });

  if (!hasMore) return null;

  return (
    <div
      ref={ref}
      className="flex min-h-12 flex-col items-center justify-center gap-2 pt-4"
    >
      {error ? (
        <>
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          <Button variant="outline" size="sm" onClick={onLoadMore}>
            {t("retry")}
          </Button>
        </>
      ) : (
        pending && (
          <StatusIndicator
            kind="running"
            aria-label={t("loadingMore")}
            title={t("loadingMore")}
          />
        )
      )}
    </div>
  );
}
