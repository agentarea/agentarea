"use client";

import { Network, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type PoliciesView = "policies" | "access";

const TABS: { value: PoliciesView; label: string; icon: typeof ShieldCheck }[] = [
  { value: "policies", label: "Policies", icon: ShieldCheck },
  { value: "access", label: "Access", icon: Network },
];

export function PoliciesViewTabs({ current }: { current: PoliciesView }) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg bg-muted p-1">
      {TABS.map(({ value, label, icon: Icon }) => {
        const active = value === current;
        return (
          <Link
            key={value}
            href={value === "policies" ? "/policies" : "/policies?view=access"}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </Link>
        );
      })}
    </div>
  );
}
