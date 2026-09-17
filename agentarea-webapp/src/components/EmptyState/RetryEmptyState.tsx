"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";

type RetryEmptyStateProps = {
  title: string;
  description?: string;
  iconsType?: React.ComponentProps<typeof EmptyState>["iconsType"];
  icons?: React.ComponentProps<typeof EmptyState>["icons"];
  /** Optional secondary way out when retrying is unlikely to help. */
  additionAction?: { label: string; href?: string };
};

/**
 * Error empty state with a working Retry.
 *
 * Server components render their failures through this so a failed load is a
 * dead end no longer -- `router.refresh()` re-runs the server render, which a
 * plain link to the same route does not reliably do.
 */
export default function RetryEmptyState({
  title,
  description,
  iconsType,
  icons,
  additionAction,
}: RetryEmptyStateProps) {
  const router = useRouter();
  const t = useTranslations("Common");

  return (
    <EmptyState
      title={title}
      description={description}
      iconsType={iconsType}
      icons={icons}
      action={{ label: t("retry"), onClick: () => router.refresh() }}
      additionAction={additionAction}
    />
  );
}
