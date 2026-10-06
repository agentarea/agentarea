"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { Loader2, Trash2, type LucideIcon } from "lucide-react";
import AccordionControl from "@/components/AccordionControl";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import ConfigSheet from "@/components/ConfigSheet";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SelectableList } from "@/components/SelectableList";
import { Accordion } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import Note from "@/components/ui/note";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";

export type AttachmentItem = {
  id: string;
  name: string;
  description?: string | null;
};

/** What a server action returns: `{ error }` on failure, anything else on success. */
export type MutationResult = { error?: unknown } | void;

/**
 * An attached item comes back from the API as an `{id, name}` reference; pair it
 * with the full record from the listing so the section can show its description
 * and icon.
 */
export function hydrateAttachments<T extends AttachmentItem>(
  refs: { id: string; name: string }[] | null | undefined,
  all: T[]
): (T | AttachmentItem)[] {
  const byId = new Map(all.map((item) => [String(item.id), item]));
  return (refs ?? []).map(
    (ref) => byId.get(String(ref.id)) ?? { id: String(ref.id), name: ref.name }
  );
}

/**
 * The write half of an attachment UI: runs an add / remove action, tracks the
 * item in flight and the last error, then lets the owner refetch.
 */
export function useAttachmentWrites<T extends AttachmentItem>(
  onChanged?: () => Promise<void> | void
) {
  const t = useTranslations("AttachmentSection");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (
    item: T,
    action: (item: T) => Promise<MutationResult>,
    verb: "add" | "remove"
  ) => {
    const label =
      verb === "add"
        ? t("addFailed", { item: item.name })
        : t("removeFailed", { item: item.name });
    setPendingId(item.id);
    setError(null);
    try {
      const result = await action(item);
      if (result && result.error) {
        setError(apiErrorMessage(result as ApiResultLike, label));
        return;
      }
    } catch (err) {
      console.error(`Failed to ${verb} attachment`, err);
      setError(`${label}: ${formatApiError(err)}`);
      return;
    } finally {
      setPendingId(null);
    }
    // The write went through; a failed refetch is its own error, not the write's.
    try {
      await onChanged?.();
    } catch (err) {
      console.error("Failed to reload after attachment change", err);
      setError(formatApiError(err));
    }
  };

  return { run, pendingId, error, setError };
}

/** The small mark in front of an item name: its own icon, or the section's. */
function ItemMark<T extends AttachmentItem>({
  item,
  icon: Icon,
  getIconSrc,
}: {
  item: T;
  icon: LucideIcon;
  getIconSrc?: (item: T) => string | undefined;
}) {
  const src = getIconSrc?.(item);
  return (
    <span className="relative grid h-4 w-4 shrink-0 place-items-center overflow-hidden">
      {src ? (
        <Image
          src={src}
          alt=""
          width={16}
          height={16}
          className="h-4 w-4 object-contain"
        />
      ) : (
        <Icon className="h-4 w-4 text-muted-foreground" />
      )}
    </span>
  );
}

function ItemTitle<T extends AttachmentItem>({
  item,
  icon,
  getIconSrc,
}: {
  item: T;
  icon: LucideIcon;
  getIconSrc?: (item: T) => string | undefined;
}) {
  return (
    <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
      <ItemMark item={item} icon={icon} getIconSrc={getIconSrc} />
      <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
        {item.name}
      </h3>
    </div>
  );
}

function ItemDetails<T extends AttachmentItem>({
  item,
  renderDetails,
}: {
  item: T;
  renderDetails?: (item: T) => ReactNode;
}) {
  return renderDetails ? (
    <>{renderDetails(item)}</>
  ) : (
    <p className="text-xs text-muted-foreground">{item.description || "—"}</p>
  );
}

type AttachmentPickerSheetProps<T extends AttachmentItem> = {
  /** Prefix for the picker's list ids, unique on the page. */
  id: string;
  icon: LucideIcon;
  sheetTitle: string;
  sheetDescription: string;
  /** Heading above the pickable list inside the sheet. */
  availableTitle: string;
  available: T[];
  attachedIds: string[];
  loading?: boolean;
  /** Shown inside the sheet when nothing can be picked. */
  emptyAvailable: ReactNode;
  onAdd: (item: T) => void;
  onRemove: (item: T) => void;
  error?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Noun on the default sheet trigger, e.g. "Skill". */
  triggerText?: string;
  /** Replaces the default trigger button. */
  triggerComponent?: ReactNode;
  className?: string;
  getIconSrc?: (item: T) => string | undefined;
  renderDetails?: (item: T) => ReactNode;
};

/**
 * The picker the agent form uses, in a side sheet: every available item, with
 * the attached ones selected; picking writes through `onAdd` / `onRemove`.
 */
export function AttachmentPickerSheet<T extends AttachmentItem>({
  id,
  icon: Icon,
  sheetTitle,
  sheetDescription,
  availableTitle,
  available,
  attachedIds,
  loading = false,
  emptyAvailable,
  onAdd,
  onRemove,
  error,
  open,
  onOpenChange,
  triggerText,
  triggerComponent,
  className,
  getIconSrc,
  renderDetails,
}: AttachmentPickerSheetProps<T>) {
  const t = useTranslations("AttachmentSection");

  return (
    <ConfigSheet
      title={sheetTitle}
      description={sheetDescription}
      triggerText={triggerText}
      triggerComponent={triggerComponent}
      className={className}
      open={open}
      onOpenChange={onOpenChange}
    >
      <div className="flex flex-col space-y-4 overflow-y-auto">
        {error && open && <FormError>{error}</FormError>}
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 text-muted-foreground" />
          {availableTitle}
        </div>
        {loading ? (
          <Note>
            <p>{t("loading")}</p>
          </Note>
        ) : available.length > 0 ? (
          <SelectableList
            items={available}
            prefix={id}
            extractTitle={(item) => (
              <ItemTitle item={item} icon={Icon} getIconSrc={getIconSrc} />
            )}
            onAdd={onAdd}
            onRemove={onRemove}
            selectedIds={attachedIds}
            renderContent={(item) => (
              <div className="space-y-2 p-2">
                <ItemDetails item={item} renderDetails={renderDetails} />
              </div>
            )}
          />
        ) : (
          <Note>{emptyAvailable}</Note>
        )}
      </div>
    </ConfigSheet>
  );
}

type AttachmentSectionProps<T extends AttachmentItem> = {
  /** Accordion id, unique on the page. */
  id: string;
  title: string;
  icon: LucideIcon;
  /** Tooltip text on the section header. */
  note?: ReactNode;
  /** Noun on the sheet trigger, e.g. "Skill". */
  triggerText: string;
  sheetTitle: string;
  sheetDescription: string;
  /** Heading above the pickable list inside the sheet. */
  availableTitle: string;
  attached: T[];
  available: T[];
  loading?: boolean;
  /** Shown in place of the attached list while it is empty. */
  emptyLabel: ReactNode;
  /** Shown inside the sheet when nothing can be picked. */
  emptyAvailable: ReactNode;
  onAdd: (item: T) => Promise<MutationResult>;
  onRemove: (item: T) => Promise<MutationResult>;
  /** Called after a write succeeds — refetch the owning resource here. */
  onChanged?: () => Promise<void> | void;
  getIconSrc?: (item: T) => string | undefined;
  renderDetails?: (item: T) => ReactNode;
};

/**
 * A titled section that attaches entities to a resource through the same picker
 * the agent form uses: header with a sheet trigger, picker list inside the
 * sheet, attached items as cards below. Writes go straight through `onAdd` /
 * `onRemove`, so it fits resources whose associations are their own endpoints.
 */
export function AttachmentSection<T extends AttachmentItem>({
  id,
  title,
  icon,
  note,
  triggerText,
  sheetTitle,
  sheetDescription,
  availableTitle,
  attached,
  available,
  loading = false,
  emptyLabel,
  emptyAvailable,
  onAdd,
  onRemove,
  onChanged,
  getIconSrc,
  renderDetails,
}: AttachmentSectionProps<T>) {
  const [accordionValue, setAccordionValue] = useState<string>(id);
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const { run, pendingId, error, setError } = useAttachmentWrites<T>(onChanged);
  const t = useTranslations("AttachmentSection");

  return (
    <AccordionControl
      id={id}
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={icon} className="cursor-pointer">
          {title}
        </FormLabel>
      }
      note={note}
      mainControl={
        <AttachmentPickerSheet
          id={id}
          icon={icon}
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
          open={isSheetOpen}
          onOpenChange={(open) => {
            setIsSheetOpen(open);
            if (!open) setError(null);
          }}
          triggerText={triggerText}
          className="ml-auto"
          getIconSrc={getIconSrc}
          renderDetails={renderDetails}
        />
      }
    >
      <div className="space-y-4">
        {error && !isSheetOpen && (
          <FormError className="mt-2">{error}</FormError>
        )}
        {attached.length > 0 ? (
          <Accordion type="multiple" id={`${id}-items`} className="space-y-2">
            {attached.map((item) => (
              <CardAccordionItem
                key={`${id}-${item.id}`}
                value={`${id}-${item.id}`}
                title={
                  <ItemTitle item={item} icon={icon} getIconSrc={getIconSrc} />
                }
                controls={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => run(item, onRemove, "remove")}
                    disabled={pendingId === item.id}
                    className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                    aria-label={t("remove", { item: item.name })}
                  >
                    {pendingId === item.id ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Trash2 />
                    )}
                  </Button>
                }
              >
                <div className="space-y-2">
                  <ItemDetails item={item} renderDetails={renderDetails} />
                </div>
              </CardAccordionItem>
            ))}
          </Accordion>
        ) : (
          <Note className="mt-2">
            <p>{emptyLabel}</p>
          </Note>
        )}
      </div>
    </AccordionControl>
  );
}
