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
      {/* The title takes what is left and wraps; the badge on the right
          keeps its one line instead of being squeezed into two. */}
      <div className="min-w-0 flex-1 space-y-1">
        <div className="text-xs font-normal uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {title}
        </h3>
      </div>
      {right && <div className="shrink-0 whitespace-nowrap">{right}</div>}
    </div>
  );
}

