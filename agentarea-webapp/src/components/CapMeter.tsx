import { cn } from "@/lib/utils";

/** Text colour for a share of a cap: neutral, then amber at 80%, red at 100%. */
export function capTone(pct: number) {
  if (pct >= 100) return "text-red-600 dark:text-red-400";
  if (pct >= 80) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

function barTone(pct: number) {
  if (pct >= 100) return "bg-[color:var(--status-danger)]";
  if (pct >= 80) return "bg-[color:var(--status-warning)]";
  return "bg-[color:var(--violet)]";
}

/** How much of a cap is spent, as a bar that turns amber and then red. */
export function CapMeter({
  pct,
  className,
}: {
  pct: number;
  className?: string;
}) {
  return (
    <div
      className={cn("h-[5px] overflow-hidden rounded-full bg-muted", className)}
    >
      <div
        className={cn("h-full rounded-full", barTone(pct))}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}
