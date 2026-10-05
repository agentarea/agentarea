"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Plus, Trash2, type LucideIcon } from "lucide-react";
import FormError from "@/components/FormError";
import {
  EmptyRow,
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import { Button } from "@/components/ui/button";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  AttachmentPickerSheet,
  useAttachmentWrites,
  type AttachmentItem,
  type MutationResult,
} from "./AttachmentSection";

type AttachmentCardProps<T extends AttachmentItem> = {
  /** Prefix for the picker's list ids, unique on the page. */
  id: string;
  title: string;
  icon: LucideIcon;
  /** Label of the "Add" trigger in the card head. */
  addLabel: string;
  sheetTitle: string;
  sheetDescription: string;
  /** Heading above the pickable list inside the sheet. */
  availableTitle: string;
  attached: T[];
  available: T[];
  loading?: boolean;
  /** Shown in place of the rows while nothing is attached. */
  emptyLabel: string;
  /** Shown inside the sheet when nothing can be picked. */
  emptyAvailable: ReactNode;
  onAdd: (item: T) => Promise<MutationResult>;
  onRemove: (item: T) => Promise<MutationResult>;
  /** Called after a write succeeds — refetch the owning resource here. */
  onChanged?: () => Promise<void> | void;
  /** The row's identity tile (an avatar). */
  renderTile: (item: T) => ReactNode;
  /** The item's page; the whole row opens it. */
  itemHref?: (item: T) => string | undefined;
  /** The row's second line; the item's description by default. */
  renderSub?: (item: T) => ReactNode;
  getIconSrc?: (item: T) => string | undefined;
  renderDetails?: (item: T) => ReactNode;
};

/**
 * What a resource has attached, as an overview section card: one row per item
 * (tile, name, description) that opens the item, with remove as the row's
 * hover action, and the picker sheet behind an "Add" trigger in the card head. The detail-page counterpart of
 * `AttachmentSection`, sharing its picker and its writes.
 */
export function AttachmentCard<T extends AttachmentItem>({
  id,
  title,
  icon: Icon,
  addLabel,
  sheetTitle,
  sheetDescription,
  availableTitle,
  attached,
  available,
  loading,
  emptyLabel,
  emptyAvailable,
  onAdd,
  onRemove,
  onChanged,
  renderTile,
  itemHref,
  renderSub,
  getIconSrc,
  renderDetails,
}: AttachmentCardProps<T>) {
  const t = useTranslations("AttachmentSection");
  const router = useWorkspaceRouter();
  const [open, setOpen] = useState(false);
  const { run, pendingId, error, setError } = useAttachmentWrites<T>(onChanged);

  return (
    <SectionCard>
      <SectionCardHead
        icon={<Icon />}
        title={title}
        count={attached.length}
        action={
          <AttachmentPickerSheet
            id={id}
            icon={Icon}
            sheetTitle={sheetTitle}
            sheetDescription={sheetDescription}
            availableTitle={availableTitle}
            available={available}
            attachedIds={attached.map((item) => item.id)}
            loading={loading}
            emptyAvailable={emptyAvailable}
            onAdd={(item) => run(item, onAdd, "add")}
            onRemove={(item) => run(item, onRemove, "remove")}
            error={error}
            open={open}
            onOpenChange={(next) => {
              setOpen(next);
              if (!next) setError(null);
            }}
            triggerComponent={
              <Button
                variant="ghost"
                size="xs"
                className="text-muted-foreground"
              >
                <Plus />
                {addLabel}
              </Button>
            }
            getIconSrc={getIconSrc}
            renderDetails={renderDetails}
          />
        }
      />

      {error && !open && (
        <div className="border-b border-border/60 px-[15px] py-2.5">
          <FormError>{error}</FormError>
        </div>
      )}

      {attached.length > 0 ? (
        attached.map((item) => {
          const href = itemHref?.(item);
          const sub = renderSub ? renderSub(item) : item.description;
          const pending = pendingId === item.id;
          return (
            <InteractiveListRow
              key={item.id}
              onClick={href ? () => router.push(href) : undefined}
              showIndicator={Boolean(href)}
              className="px-[15px] py-[11px]"
              dividerClassName="border-b border-border/60 last:border-b-0"
              start={renderTile(item)}
              // Keep the spinner on screen while the removal is in flight.
              forceHoverActionsVisible={pending}
              hoverActionsClassName="bg-gradient-to-l from-muted/60 via-muted/60 to-transparent dark:from-zinc-800/50 dark:via-zinc-800/50"
              hoverActions={
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => run(item, onRemove, "remove")}
                      disabled={pending}
                      className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive dark:hover:bg-red-500/15 dark:hover:text-red-200"
                      aria-label={t("remove", { item: item.name })}
                    >
                      {pending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    {t("remove", { item: item.name })}
                  </TooltipContent>
                </Tooltip>
              }
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] font-medium">
                  {item.name}
                </div>
                {sub && (
                  <div className="mt-px truncate text-[11px] text-muted-foreground">
                    {sub}
                  </div>
                )}
              </div>
            </InteractiveListRow>
          );
        })
      ) : (
        <EmptyRow text={emptyLabel} />
      )}
    </SectionCard>
  );
}
