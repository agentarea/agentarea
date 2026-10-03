import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** One labelled setting: icon, title and description on the left, the control on the right. */
export default function SettingsRow({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "group relative flex flex-col md:flex-row md:items-start gap-3 w-full p-4",
        "bg-white dark:bg-zinc-900",
        "border border-zinc-200/60 dark:border-zinc-800",
        "rounded-md",
        "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
        "relative overflow-hidden"
      )}
    >
      <div
        className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: `repeating-linear-gradient(
             -45deg,
             currentColor,
             currentColor 1px,
             transparent 1px,
             transparent 10px
           )`,
        }}
      />
      <div className="flex items-center gap-3 z-10">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10">
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
            {title}
          </span>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {description}
          </span>
        </div>
      </div>

      <div className="z-10 ml-11 md:ml-auto">{children}</div>
    </div>
  );
}
