"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import { ToolbarButton } from "@/components/ui/toolbar";
import { cn } from "@/lib/utils";

/**
 * Reload what a subheader toolbar's page shows: an icon-only toolbar button,
 * its icon spinning and the button off while the reload runs.
 */
export default function ToolbarRefreshButton({
  onRefresh,
  refreshing = false,
}: {
  onRefresh: () => void;
  refreshing?: boolean;
}) {
  const t = useTranslations("Common");

  return (
    <ToolbarButton
      onClick={onRefresh}
      disabled={refreshing}
      aria-label={t("refresh")}
      title={t("refresh")}
      className="justify-center px-0 disabled:hover:bg-transparent"
    >
      <RefreshCw
        className={cn(
          "h-3.5 w-3.5 text-muted-foreground",
          refreshing && "animate-spin"
        )}
      />
    </ToolbarButton>
  );
}
