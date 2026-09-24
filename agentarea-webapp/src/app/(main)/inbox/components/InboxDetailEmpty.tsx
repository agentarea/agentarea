"use client";

import { useTranslations } from "next-intl";
import { CircleAlert, CircleCheck, Inbox } from "lucide-react";
import EmptyState from "@/components/EmptyState";

interface InboxDetailEmptyProps {
  pendingCount: number;
  onOpenNextPending: () => void;
}

/**
 * The reading pane with nothing selected. Quiet like Linear's — no card, no
 * border — but built from our EmptyState tiles, echoing the filter icons above
 * the list, and it offers the one useful next step: the next approval.
 */
export function InboxDetailEmpty({
  pendingCount,
  onOpenNextPending,
}: InboxDetailEmptyProps) {
  const t = useTranslations("InboxPage.detailEmpty");
  const hasPending = pendingCount > 0;

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <EmptyState
        icons={[CircleAlert, Inbox, CircleCheck]}
        accentClassName="text-primary"
        title={t("title")}
        description={
          hasPending ? t("pending", { count: pendingCount }) : t("clear")
        }
        action={
          hasPending
            ? { label: t("openNext"), onClick: onOpenNextPending }
            : undefined
        }
        className="max-w-[420px] border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent"
      />
    </div>
  );
}
