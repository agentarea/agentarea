import type { Direction } from "@shared/books";
import { money } from "@/lib/format";
import { cn } from "@kit/lib/utils";

/** An amount in tabular figures; with a direction it is signed and colored the way a ledger reads. */
export function Money({
  minor,
  currency,
  locale,
  direction,
  className,
}: {
  minor: number;
  currency: string;
  locale: string;
  direction?: Direction;
  className?: string;
}) {
  const text = money(Math.abs(minor), currency, locale);
  const negative = direction === "out" || (direction === undefined && minor < 0);
  const sign = direction === "in" ? "+" : negative ? "−" : "";
  return (
    <span
      className={cn(
        "tabular whitespace-nowrap",
        direction === "in" && "text-success",
        direction === "transfer" && "text-muted-foreground",
        direction === undefined && minor < 0 && "text-danger",
        className,
      )}
    >
      {sign}
      {text}
    </span>
  );
}
