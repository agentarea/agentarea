"use client";

import { useTranslations } from "next-intl";
import { Check, Pencil, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * A section card head's control for a list edited in place: Edit (or Add on an
 * empty list) while closed, Cancel and Save while its draft is open.
 */
export function SectionEditAction({
  open,
  hasRows,
  busy,
  onOpen,
  onCancel,
  onSave,
  saveLabel,
}: {
  open: boolean;
  hasRows: boolean;
  busy: boolean;
  onOpen: () => void;
  onCancel: () => void;
  onSave: () => void;
  /** Names what Save commits, for screen readers. */
  saveLabel: string;
}) {
  const tCommon = useTranslations("Common");

  if (!open) {
    return (
      <Button
        variant="ghost"
        size="xs"
        className="text-muted-foreground"
        onClick={onOpen}
      >
        {hasRows ? <Pencil /> : <Plus />}
        {hasRows ? tCommon("edit") : tCommon("add")}
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="xs"
        className="text-muted-foreground"
        onClick={onCancel}
        disabled={busy}
      >
        {tCommon("cancel")}
      </Button>
      {/* Light like Cancel; the accent text alone marks it as the commit. */}
      <Button
        variant="ghost"
        size="xs"
        className="px-2 font-medium text-primary hover:text-primary"
        onClick={onSave}
        isLoading={busy}
        disabled={busy}
        aria-label={saveLabel}
      >
        {!busy && <Check />}
        {tCommon("save")}
      </Button>
    </div>
  );
}
