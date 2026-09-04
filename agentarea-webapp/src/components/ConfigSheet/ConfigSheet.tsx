import React, { ReactNode, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

type ConfigSheetProps = {
  title: string;
  description: string;
  children: ReactNode;
  triggerText?: string;
  triggerIcon?: ReactNode;
  triggerComponent?: ReactNode;
  triggerClassName?: string;
  className?: string;
  open?: boolean; // External control of open state
  onOpenChange?: (open: boolean) => void; // Optional callback for parent component
  triggerRef?: React.RefObject<HTMLButtonElement | null>; // Optional ref to trigger button
  shortcut?: string; // Keyboard shortcut (e.g., "t" for Cmd+T)
};

const ConfigSheet = ({
  title,
  className,
  triggerComponent,
  triggerClassName,
  description,
  children,
  triggerText = "Add",
  triggerIcon = <Plus className="h-4 w-4" />,
  open,
  onOpenChange,
  triggerRef,
  shortcut,
}: ConfigSheetProps) => {
  const [internalIsOpen, setInternalIsOpen] = useState(false);

  // Use external open state if provided, otherwise use internal state
  const isOpen = open !== undefined ? open : internalIsOpen;

  const handleOpenChange = (newOpen: boolean) => {
    setInternalIsOpen(newOpen);
    onOpenChange?.(newOpen);
  };

  // Handle keyboard shortcut (Option/Alt + key)
  useEffect(() => {
    if (!shortcut) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Use Option/Alt key to avoid conflicts with browser shortcuts
      if (e.altKey && e.key.toLowerCase() === shortcut.toLowerCase()) {
        // Don't trigger if user is typing in an input
        const target = e.target as HTMLElement;
        const isInputField = target.tagName === "INPUT" ||
                            target.tagName === "TEXTAREA" ||
                            target.isContentEditable;

        if (!isInputField) {
          e.preventDefault();
          e.stopPropagation();
          // Toggle the sheet
          const newState = open !== undefined ? !open : !internalIsOpen;
          setInternalIsOpen(newState);
          onOpenChange?.(newState);
        }
      }
    };

    // Use capture phase to intercept before other handlers
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [shortcut, open, internalIsOpen, onOpenChange]);

  // Helper to determine if outside click should be ignored (e.g., when interacting with controls)
  const shouldIgnoreOutsideClick = (target: HTMLElement) =>
    !!target.closest(
      'button, input, select, textarea, a, [role="button"], label, [data-radix-select-content], [data-radix-scroll-area]'
    );

  return (
    <Sheet modal={false} open={isOpen} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        {triggerComponent ? (
          triggerComponent
        ) : (
          <Button size="xs" ref={triggerRef} className={cn("gap-1.5", triggerClassName)}>
            {triggerIcon}
            {triggerText}
            {shortcut && (
              <Badge
                variant="outline"
                className="ml-1 h-4 border-muted-foreground/30 bg-background/50 px-1 py-0 text-[10px] font-normal text-muted-foreground"
              >
                ⌥{shortcut.toUpperCase()}
              </Badge>
            )}
          </Button>
        )}
      </SheetTrigger>
      <SheetContent
        className={cn(
          "flex w-full flex-col overflow-y-hidden pb-0 sm:w-[540px] md:min-w-[500px]",
          className
        )}
        hideOverlay
        onPointerDownOutside={(e) => {
          const target = e.target as HTMLElement;
          if (shouldIgnoreOutsideClick(target)) {
            e.preventDefault();
          }
        }}
        onInteractOutside={(e) => {
          const target = e.target as HTMLElement;
          if (shouldIgnoreOutsideClick(target)) {
            e.preventDefault();
          }
        }}
      >
        <SheetHeader className="">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className="text-xs">{description}</SheetDescription>
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
};

export default ConfigSheet;
