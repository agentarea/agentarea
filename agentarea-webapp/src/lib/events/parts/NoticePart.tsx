import React from "react";
import { useTranslations } from "next-intl";
import { FoldVertical } from "lucide-react";
import type { Part } from "../contract";

/** A divider marking where the run compacted its context. */
export const NoticePart: React.FC<{ part: Part }> = ({ part }) => {
  const t = useTranslations("Chat.conversation");
  const count = Number(part.data.messages_compacted);

  return (
    <div
      role="note"
      className="flex items-center gap-3 px-2 text-[11px] leading-4 text-muted-foreground"
    >
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span className="flex min-w-0 items-center gap-1.5">
        <FoldVertical aria-hidden className="h-3 w-3 shrink-0" />
        <span className="min-w-0">{t("compacted", { count })}</span>
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </div>
  );
};

export default NoticePart;
