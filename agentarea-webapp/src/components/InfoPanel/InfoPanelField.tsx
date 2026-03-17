"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export default function InfoPanelField({
  label,
  icon: Icon,
  children,
  className,
  labelClassName,
}: {
  label: ReactNode;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
  labelClassName?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <div
        className={cn(
          Icon
            ? "flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
            : "text-[11px] font-medium uppercase tracking-wide text-muted-foreground",
          labelClassName
        )}
      >
        {Icon && <Icon className="h-3 w-3 text-primary" />}
        {label}
      </div>
      {children}
    </div>
  );
}

