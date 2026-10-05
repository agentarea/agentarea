"use client";

import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface InboxSelectionBarProps {
  checkedCount: number;
  onApprove: () => void;
  onReject: () => void;
  onClear: () => void;
}

export function InboxSelectionBar({
  checkedCount,
  onApprove,
  onReject,
  onClear,
}: InboxSelectionBarProps) {
  const t = useTranslations("InboxPage");

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-primary/10 px-3 py-2">
      <span className="mr-auto text-[12.5px] font-semibold text-primary">
        {t("selection.count", { count: checkedCount })}
      </span>
      <Button size="xs" className="shrink-0" onClick={onApprove}>
        <Check />
        {t("approve")}
      </Button>
      <Button
        size="xs"
        variant="destructiveOutline"
        className="shrink-0"
        onClick={onReject}
      >
        <X />
        {t("reject")}
      </Button>
      <Button
        size="xs"
        variant="ghost"
        className="shrink-0 text-muted-foreground"
        onClick={onClear}
      >
        {t("selection.clear")}
      </Button>
    </div>
  );
}
