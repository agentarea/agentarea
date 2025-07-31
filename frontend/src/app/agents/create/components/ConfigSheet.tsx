import React, { ReactNode, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
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
  triggerRef
}: ConfigSheetProps) => {
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  
  // Use external open state if provided, otherwise use internal state
  const isOpen = open !== undefined ? open : internalIsOpen;

  const handleOpenChange = (open: boolean) => {
    if (open !== undefined) {
      setInternalIsOpen(open);
    }
    onOpenChange?.(open); // Call parent callback if provided
  };

  // Helper to determine if outside click should be ignored (e.g., when interacting with controls)
  const shouldIgnoreOutsideClick = (target: HTMLElement) =>
    !!target.closest(
      'button, input, select, textarea, a, [role="button"], label, [data-radix-select-content], [data-radix-scroll-area]'
    );

  return (
    <Sheet modal={false} open={isOpen} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        {
            triggerComponent ? triggerComponent : (
                <Button size="xs" ref={triggerRef} className={triggerClassName}>
                    {triggerIcon}
                    {triggerText}
                </Button>
            )
        }
      </SheetTrigger>
      <SheetContent
        className={cn("w-full flex flex-col sm:w-[540px] overflow-y-hidden pb-0", className)}
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
        <SheetHeader className="mb-[12px] md:mb-[24px]">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className="text-xs">{description}</SheetDescription>
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
};

export default ConfigSheet; 