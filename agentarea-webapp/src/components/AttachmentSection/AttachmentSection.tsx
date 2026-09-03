"use client";

import { useState, type ReactNode } from "react";
import Image from "next/image";
import { Loader2, Trash2, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import AccordionControl from "@/components/AccordionControl";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SelectableList } from "@/components/SelectableList";
import { Accordion } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import Note from "@/components/ui/note";

export type AttachmentItem = {
  id: string;
  name: string;
  description?: string | null;
};

/** What a server action returns: `{ error }` on failure, anything else on success. */
type MutationResult = { error?: unknown } | void;

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
  const [pendingId, setPendingId] = useState<string | null>(null);

  const Icon = icon;
  const attachedIds = attached.map((item) => item.id);

  const run = async (
    item: T,
    action: (item: T) => Promise<MutationResult>,
    verb: "add" | "remove"
  ) => {
    setPendingId(item.id);
    try {
      const result = await action(item);
      if (result && result.error) {
        toast.error(`Failed to ${verb} ${triggerText.toLowerCase()}`);
        return;
      }
      await onChanged?.();
    } finally {
      setPendingId(null);
    }
  };

  const Mark = ({ item }: { item: T }) => {
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
  };

  const itemTitle = (item: T) => (
    <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
      <Mark item={item} />
      <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
        {item.name}
      </h3>
    </div>
  );

  const details = (item: T) =>
    renderDetails ? (
      renderDetails(item)
    ) : (
      <p className="text-xs text-muted-foreground">{item.description || "—"}</p>
    );

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
        <ConfigSheet
          title={sheetTitle}
          description={sheetDescription}
          triggerText={triggerText}
          className="ml-auto"
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
        >
          <div className="flex flex-col space-y-4 overflow-y-auto">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Icon className="h-4 w-4 text-muted-foreground" />
              {availableTitle}
            </div>
            {loading ? (
              <Note>
                <p>Loading…</p>
              </Note>
            ) : available.length > 0 ? (
              <SelectableList
                items={available}
                prefix={id}
                extractTitle={itemTitle}
                onAdd={(item) => run(item, onAdd, "add")}
                onRemove={(item) => run(item, onRemove, "remove")}
                selectedIds={attachedIds}
                renderContent={(item) => (
                  <div className="space-y-2 p-2">{details(item)}</div>
                )}
              />
            ) : (
              <Note>{emptyAvailable}</Note>
            )}
          </div>
        </ConfigSheet>
      }
    >
      <div className="space-y-4">
        {attached.length > 0 ? (
          <Accordion type="multiple" id={`${id}-items`} className="space-y-2">
            {attached.map((item) => (
              <CardAccordionItem
                key={`${id}-${item.id}`}
                value={`${id}-${item.id}`}
                title={itemTitle(item)}
                controls={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => run(item, onRemove, "remove")}
                    disabled={pendingId === item.id}
                    className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                    aria-label={`Remove ${item.name}`}
                  >
                    {pendingId === item.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                }
              >
                <div className="space-y-2">{details(item)}</div>
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
