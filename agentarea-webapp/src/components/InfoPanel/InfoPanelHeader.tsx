"use client";

import type { ReactNode } from "react";

export default function InfoPanelHeader({
  label,
  title,
  right,
  className,
}: {
  label: ReactNode;
  title: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-start justify-between gap-3 px-3 pb-3 pt-3 ${className || ""}`}>
      <div className="space-y-1">
        <div className="text-xs font-normal uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {title}
        </h3>
      </div>
      {right}
    </div>
  );
}

