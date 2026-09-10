import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Overview building blocks for the agent detail page: a bordered section
 * card with a compact icon+title head, and the four-up stat strip whose cells
 * are separated by dashed board lines. Colors come from the theme tokens only.
 */

export function SectionCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-[3px] border border-border bg-background",
        className
      )}
    >
      {children}
    </div>
  );
}

export function SectionCardHead({
  icon,
  title,
  link,
}: {
  icon: ReactNode;
  title: string;
  link?: { label: string; href: string };
}) {
  return (
    <div className="flex items-center gap-[9px] border-b border-border/60 px-[15px] py-[11px]">
      <span className="grid h-[23px] w-[23px] shrink-0 place-items-center rounded bg-muted text-foreground/80 [&>svg]:h-3.5 [&>svg]:w-3.5">
        {icon}
      </span>
      <span className="flex-1 text-[13px] font-semibold">{title}</span>
      {link && (
        <Button
          asChild
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
        >
          <Link href={link.href}>
            {link.label}
            <ArrowUpRight />
          </Link>
        </Button>
      )}
    </div>
  );
}

export function EmptyRow({
  text,
  action,
}: {
  text: string;
  action?: { label: string; href: string };
}) {
  return (
    <div className="px-[15px] py-7 text-center text-[12px] text-muted-foreground">
      {text}
      {action && (
        <>
          {" "}
          <Link
            href={action.href}
            className="font-medium text-foreground underline-offset-2 hover:underline"
          >
            {action.label}
          </Link>
        </>
      )}
    </div>
  );
}

/* ------------------------------ stat strip ------------------------------ */

export function StatStrip({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 grid grid-cols-2 overflow-hidden rounded-[3px] border border-border bg-background lg:grid-cols-4">
      {children}
    </div>
  );
}

export function Stat({
  icon,
  label,
  value,
  unit,
  bar,
  sub,
  subTone = "muted",
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  unit?: ReactNode;
  /** Progress fill: percent (0–100) and a CSS color. Omit to leave the slot empty. */
  bar?: { pct: number; color: string } | null;
  sub: ReactNode;
  subTone?: "muted" | "up";
}) {
  return (
    <div
      className={cn(
        "min-w-0 border-dashed px-4 py-[13px] [border-color:var(--board-line)]",
        // 2-up on small screens: dashed divider on even cells + a top divider on the second row
        "even:border-l [&:nth-child(n+3)]:border-t",
        // 4-up on large screens: dashed divider on every cell but the first
        "lg:border-l lg:first:border-l-0 lg:[&:nth-child(n+3)]:border-t-0"
      )}
    >
      <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground [&>svg]:h-[13px] [&>svg]:w-[13px] [&>svg]:text-muted-foreground/70">
        {icon}
        {label}
      </div>
      <div className="mt-[7px] flex items-baseline gap-1.5 leading-none">
        <span className="font-mono text-[24px] font-medium tracking-[-0.03em] tabular-nums">
          {value}
        </span>
        {unit != null && (
          <span className="text-[12px] font-medium text-muted-foreground">
            {unit}
          </span>
        )}
      </div>
      <div className="mt-2.5 h-[5px] overflow-hidden rounded-[2px]">
        {bar && (
          <div className="h-full w-full rounded-[2px] bg-muted">
            <span
              className="block h-full rounded-[2px]"
              style={{
                width: `${Math.max(0, Math.min(100, bar.pct))}%`,
                background: bar.color,
              }}
            />
          </div>
        )}
      </div>
      <div
        className={cn(
          "mt-2 truncate text-[11px]",
          subTone === "up"
            ? "text-[color:var(--status-success)]"
            : "text-muted-foreground/70"
        )}
      >
        {sub}
      </div>
    </div>
  );
}
