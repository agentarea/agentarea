"use client";

import type { HTMLAttributes, ReactNode } from "react";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * "Blueprint" sheet used inside dialogs: dashed side rails filled with a
 * fine diagonal hatch (styles live in globals.css as `.conn-bp`). Put a
 * {@link BlueprintDivider} at the top/bottom (and between sections) to get
 * the full-width dashed rule with crop-mark crosses at the rails.
 */
export function BlueprintSheet({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("conn-bp", className)} {...props} />;
}

/** Full-width dashed divider with crop-mark crosses at the side rails. */
export function BlueprintDivider() {
  return (
    <div className="conn-bp-div" aria-hidden>
      <span className="conn-bp-mkp l" />
      <span className="conn-bp-mkp r" />
    </div>
  );
}

/** Form fields on the sheet, between two dashed rules. */
export function BlueprintFields({ children }: { children: ReactNode }) {
  return (
    <BlueprintSheet className="min-w-0" style={{ paddingBottom: 0 }}>
      <BlueprintDivider />
      <div className="relative z-[1] min-w-0 space-y-5 px-4 py-5">
        {children}
      </div>
      <BlueprintDivider />
    </BlueprintSheet>
  );
}

type BlueprintDialogContentProps = {
  title: ReactNode;
  description?: ReactNode;
  /** Footer text on the left. */
  note?: ReactNode;
  /** Footer buttons on the right. */
  actions?: ReactNode;
  /** What sits on the sheet — usually {@link BlueprintFields}. */
  children: ReactNode;
};

/** Dialog body in the blueprint look; goes inside a `<Dialog>`. */
export function BlueprintDialogContent({
  title,
  description,
  note,
  actions,
  children,
}: BlueprintDialogContentProps) {
  return (
    <DialogContent className="min-w-0 max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-[496px] sm:rounded-[10px]">
      <DialogHeader className="space-y-1.5 px-6 pb-4 pt-5">
        <DialogTitle>{title}</DialogTitle>
        {description ? (
          <DialogDescription>{description}</DialogDescription>
        ) : null}
      </DialogHeader>
      {children}
      {note || actions ? (
        <DialogFooter
          className={cn(
            "px-6 py-4 sm:items-center",
            note && "sm:justify-between"
          )}
        >
          {note ? <p className="note text-left">{note}</p> : null}
          {actions}
        </DialogFooter>
      ) : null}
    </DialogContent>
  );
}
