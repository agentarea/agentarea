"use client";

import * as React from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type TableRowActionProps = Omit<ButtonProps, "size" | "children"> & {
  icon: React.ReactNode;
  /** Label; below `sm` only the icon shows and the label stays for screen readers. */
  children: React.ReactNode;
};

/**
 * Row button that shows while the row is hovered (Table rows carry `group`),
 * while it has keyboard focus, and while the dialog it opens is open.
 */
export const TableRowAction = React.forwardRef<
  HTMLButtonElement,
  TableRowActionProps
>(
  (
    { className, variant = "primaryOutline", icon, children, ...props },
    ref
  ) => (
    <Button
      ref={ref}
      variant={variant}
      size="xs"
      className={cn(
        "px-2 opacity-0 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100",
        // Touch screens have no hover to reveal it, so there it always shows.
        "[@media(hover:none)]:opacity-100",
        className
      )}
      {...props}
    >
      {icon}
      <span className="max-sm:sr-only">{children}</span>
    </Button>
  )
);
TableRowAction.displayName = "TableRowAction";
