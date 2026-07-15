import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Board layout — a full-bleed 2×2 dashed line-grid with technical
 * "registration" markers (crosses where dashed lines meet the outer edge,
 * a ring at the interior intersection). It mirrors the governance-board
 * aesthetic used across the redesign (see Dashboard).
 *
 * On large screens it fills its (relatively-positioned) parent and each cell
 * manages its own overflow. Below `lg` it collapses to a single stacked column
 * with plain dashed separators and the markers are hidden.
 *
 * Reusable: pass any four nodes; tweak the vertical split with `leftFraction`.
 */

type PlusPos = "tl" | "tr" | "bl" | "br";

/** A small crop-mark cross drawn with two thin bars (matches the design). */
function PlusMark({ pos }: { pos: PlusPos }) {
  const place: Record<PlusPos, string> = {
    tl: "left-0 top-0 -translate-x-1/2 -translate-y-1/2",
    tr: "right-0 top-0 translate-x-1/2 -translate-y-1/2",
    bl: "left-0 bottom-0 -translate-x-1/2 translate-y-1/2",
    br: "right-0 bottom-0 translate-x-1/2 translate-y-1/2",
  };
  return (
    <span
      aria-hidden
      className={cn("pointer-events-none absolute z-[6] hidden h-[11px] w-[11px] lg:block", place[pos])}
      style={{
        background:
          "linear-gradient(var(--board-crop),var(--board-crop)) center / 1.4px 11px no-repeat," +
          "linear-gradient(var(--board-crop),var(--board-crop)) center / 11px 1.4px no-repeat",
      }}
    />
  );
}

/** A ring marker for the interior line intersection. */
function RingMark({ pos }: { pos: PlusPos }) {
  const place: Record<PlusPos, string> = {
    tl: "left-0 top-0 -translate-x-1/2 -translate-y-1/2",
    tr: "right-0 top-0 translate-x-1/2 -translate-y-1/2",
    bl: "left-0 bottom-0 -translate-x-1/2 translate-y-1/2",
    br: "right-0 bottom-0 translate-x-1/2 translate-y-1/2",
  };
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute z-[6] hidden h-[9px] w-[9px] rounded-full border-[1.5px] bg-background lg:block",
        place[pos]
      )}
      style={{ borderColor: "var(--board-crop)" }}
    />
  );
}

export function BoardCell({
  children,
  padded = true,
  className,
  markers,
}: {
  children: ReactNode;
  /** Adds the default cell padding. Turn off for full-bleed scrolling lists. */
  padded?: boolean;
  className?: string;
  /** Crop marks rendered at this cell's corners (desktop only). */
  markers?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "relative flex min-h-0 min-w-0 flex-col",
        padded && "px-6 pb-4 pt-3.5",
        className
      )}
    >
      {children}
      {markers}
    </section>
  );
}

export function BoardGrid({
  topLeft,
  topRight,
  bottomLeft,
  bottomRight,
  leftFraction = 0.6,
  className,
}: {
  topLeft: ReactNode;
  topRight: ReactNode;
  bottomLeft: ReactNode;
  bottomRight: ReactNode;
  /** Vertical divider position as a fraction of width (default 0.6 → 1.5fr : 1fr). */
  leftFraction?: number;
  className?: string;
}) {
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `minmax(0, ${leftFraction}fr) minmax(0, ${1 - leftFraction}fr)`,
    gridTemplateRows: "minmax(0, auto) minmax(0, 1fr)",
  };
  const dashed = "border-dashed [border-color:var(--board-line)]";

  return (
    <div className={cn("relative w-full lg:h-full", className)}>
      <div className="flex flex-col lg:absolute lg:inset-0 lg:grid" style={gridStyle}>
        {/* top-left */}
        <BoardCell
          padded
          className={cn("border-b", dashed, "lg:border-r")}
          markers={
            <>
              <PlusMark pos="bl" />
              <RingMark pos="br" />
            </>
          }
        >
          {topLeft}
        </BoardCell>

        {/* top-right */}
        <BoardCell
          padded
          className={cn("border-b", dashed)}
          markers={<PlusMark pos="br" />}
        >
          {topRight}
        </BoardCell>

        {/* bottom-left */}
        <BoardCell padded={false} className={cn("border-b lg:border-b-0 lg:border-r", dashed)}>
          {bottomLeft}
        </BoardCell>

        {/* bottom-right */}
        <BoardCell padded={false}>{bottomRight}</BoardCell>
      </div>

      {/* board-level vertical-divider crop marks (desktop only) */}
      <span
        aria-hidden
        className="pointer-events-none absolute top-0 z-[6] hidden h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 lg:block"
        style={{
          left: `${leftFraction * 100}%`,
          background:
            "linear-gradient(var(--board-crop),var(--board-crop)) center / 1.4px 11px no-repeat," +
            "linear-gradient(var(--board-crop),var(--board-crop)) center / 11px 1.4px no-repeat",
        }}
      />
      <span
        aria-hidden
        className="pointer-events-none absolute bottom-0 z-[6] hidden h-[11px] w-[11px] -translate-x-1/2 translate-y-1/2 lg:block"
        style={{
          left: `${leftFraction * 100}%`,
          background:
            "linear-gradient(var(--board-crop),var(--board-crop)) center / 1.4px 11px no-repeat," +
            "linear-gradient(var(--board-crop),var(--board-crop)) center / 11px 1.4px no-repeat",
        }}
      />
    </div>
  );
}
