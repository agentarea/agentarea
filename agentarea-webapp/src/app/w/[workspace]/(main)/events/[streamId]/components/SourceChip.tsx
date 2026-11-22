"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { StreamSourceResponse } from "@/api/client/types.gen";
import DeleteButton from "@/components/DeleteButton";
import SourceTypeMark from "@/components/SourceTypeMark";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { ApiResultLike } from "@/lib/api-errors";
import type { SourceType } from "@/lib/sourceTypes";
import SourceSenders from "./SourceSenders";

/** One source of the stream as a chip; its URL, senders and delete open from it. */
export default function SourceChip({
  streamId,
  source,
  type,
  chosenByOther,
  onDelete,
  polledAt,
}: {
  streamId: string;
  source: StreamSourceResponse;
  type: SourceType | undefined;
  chosenByOther: boolean;
  /** Absent for a source no one may delete. */
  onDelete?: (sourceId: string) => Promise<ApiResultLike>;
  polledAt: ReactNode;
}) {
  const t = useTranslations("EventsPage.sources");
  const name = type?.name ?? source.source_type ?? source.kind;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="xs" variant="outline" className="max-w-60 gap-1.5 px-2">
          <SourceTypeMark
            type={type}
            slug={source.source_type}
            inline
            className="h-4 w-4 shrink-0"
          />
          <span className="truncate">{name}</span>
          {source.poll_error && (
            <StatusIndicator
              kind="failed"
              size="sm"
              role="img"
              aria-label={t("pollFailed")}
              title={t("pollFailed")}
            />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-96 max-w-[calc(100vw-2rem)] space-y-3 p-3"
      >
        <div className="flex min-w-0 items-center gap-2">
          <SourceTypeMark type={type} slug={source.source_type} size={24} />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{name}</p>
            {source.kind === "poll" ? (
              <p className="note truncate">
                {polledAt
                  ? t.rich("polledAt", { time: () => polledAt })
                  : t("notPolledYet")}
              </p>
            ) : (
              type?.verification_header && (
                <p className="note truncate">
                  {t("signedWithHeader", { header: type.verification_header })}
                </p>
              )
            )}
          </div>
        </div>
        {source.webhook_url && <CopyableText text={source.webhook_url} />}
        {source.poll_error && (
          <p role="alert" className="break-words text-xs text-destructive">
            {t("pollError", { error: source.poll_error })}
          </p>
        )}
        {type?.admits_senders && (
          <SourceSenders
            streamId={streamId}
            sourceId={source.id}
            senders={source.senders}
            chosenByOther={chosenByOther}
          />
        )}
        {onDelete && (
          <div className="flex justify-end border-t border-zinc-200 pt-3 dark:border-zinc-700">
            <DeleteButton
              itemId={source.id}
              itemName={name}
              onDelete={onDelete}
              title={t("deleteTitle")}
              description={t("deleteDescription", { name })}
              size="xs"
            />
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
