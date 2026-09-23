"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ModalFeaturedIcon } from "./ModalFeaturedIcon";

interface BaseModalProps {
  title: string | React.ReactNode;
  description: string | React.ReactNode;
  /** Trigger element. Omit when the dialog is driven by `open`/`onOpenChange`. */
  children?: React.ReactNode;
  onConfirm: () => void | Promise<void>;
  type: "delete" | "confirm";
  /** Overrides the default "Delete"/"Confirm" label on the confirm button. */
  confirmLabel?: React.ReactNode;
  /** Keeps the confirm button disabled, e.g. when the action would be refused. */
  confirmDisabled?: boolean;
  /**
   * Controlled mode — open the dialog from somewhere that can't host a
   * trigger (a dropdown-menu item, a keyboard shortcut…). Both must be passed.
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export default function BaseModal({
  title,
  description,
  children,
  onConfirm,
  type,
  confirmLabel,
  confirmDisabled,
  open,
  onOpenChange,
}: BaseModalProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [internalOpen, setInternalOpen] = useState(false);
  const tCommon = useTranslations("Common");

  const controlled = open !== undefined && onOpenChange !== undefined;
  const isOpen = controlled ? open : internalOpen;
  const setIsOpen = controlled ? onOpenChange : setInternalOpen;

  const handleConfirm = async () => {
    setIsLoading(true);
    try {
      await onConfirm();
    } finally {
      setIsLoading(false);
    }
    setIsOpen(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      {children ? <DialogTrigger asChild>{children}</DialogTrigger> : null}
      <DialogContent className="max-w-[400px] overflow-hidden">
        <ModalFeaturedIcon type={type === "delete" ? "delete" : "success"} />
        <DialogHeader className="relative z-10 mt-3">
          <DialogTitle className="pb-2">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsOpen(false)}
            disabled={isLoading}
          >
            {tCommon("cancel")}
          </Button>
          <Button
            size="sm"
            onClick={handleConfirm}
            disabled={isLoading || confirmDisabled}
            variant={type === "delete" ? "destructive" : "default"}
          >
            {confirmLabel ??
              (type === "delete" ? tCommon("delete") : tCommon("confirm"))}
            {isLoading && <Loader2 className="animate-spin" />}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
