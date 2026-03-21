"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export default function InfoPanelBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("space-y-4 px-3.5 py-3 text-xs", className)}>{children}</div>;
}

