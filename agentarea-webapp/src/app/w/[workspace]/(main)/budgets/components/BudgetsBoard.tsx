import type { CSSProperties, ReactNode } from "react";
import { BoardCell, BoardCrossMark, BoardRingMark } from "@/components/board";
import { cn } from "@/lib/utils";

/**
 * Budgets board — a line-grid variant of the governance-board aesthetic used on
 * the Dashboard. Two cells share the top row (Spend | Month outlook) split by a
 * vertical dashed divider, and a full-bleed cap card spans the bottom row.
 *
 * On large screens it renders as a two-row grid sized by its content; below
 * `lg` it collapses to a single stacked column with plain dashed separators and
 * the registration crop-marks are hidden.
 */

/** Left column fraction → 1.55fr : 1fr split, matching the design. */
const LEFT_FRACTION = 1.55 / 2.55;

export function BudgetsBoard({
  spend,
  outlook,
  capCard,
}: {
  spend: ReactNode;
  outlook: ReactNode;
  capCard: ReactNode;
}) {
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `minmax(0, ${LEFT_FRACTION}fr) minmax(0, ${1 - LEFT_FRACTION}fr)`,
    gridTemplateRows: "minmax(0, 1fr) minmax(0, auto)",
  };
  const dashed = "border-dashed [border-color:var(--board-line)]";

  return (
    <div className="relative w-full">
      <div className="flex flex-col lg:grid" style={gridStyle}>
        {/* top-left — Spend */}
        <BoardCell
          padded
          className={cn("border-b", dashed, "lg:border-r")}
          markers={
            <BoardRingMark className="right-0 bottom-0 translate-x-1/2 translate-y-1/2" />
          }
        >
          {spend}
        </BoardCell>

        {/* top-right — Month outlook */}
        <BoardCell padded className={cn("border-b", dashed)}>
          {outlook}
        </BoardCell>

        {/* bottom — full-width cap card */}
        <BoardCell padded className="lg:col-span-2">
          {capCard}
        </BoardCell>
      </div>

      {/* vertical-divider crop marks (desktop only) */}
      <BoardCrossMark
        className="top-0 -translate-x-1/2 -translate-y-1/2"
        style={{ left: `${LEFT_FRACTION * 100}%` }}
      />
    </div>
  );
}
