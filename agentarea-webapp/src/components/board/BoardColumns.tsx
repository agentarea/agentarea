import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { BoardCell } from "./BoardCell";
import { BoardCrossMark, BoardRingMark } from "./BoardMarker";

const LEFT_EDGE = "left-0 bottom-0 -translate-x-1/2 translate-y-1/2";
const RIGHT_EDGE = "right-0 bottom-0 translate-x-1/2 translate-y-1/2";

/**
 * Board layout in two independent columns — a dashed line-grid
 * where each column stacks its own sections, so a tall section on one side
 * never stretches the other. On a desktop the board fills the height it is
 * given and the last section of each column takes what is left, keeping the
 * vertical divider unbroken.
 *
 * Sections draw their own padding. Below `lg` the left column stacks above the
 * right one and the markers are hidden.
 */
export function BoardColumns({
  left,
  right,
  leftFraction = 0.6,
  className,
}: {
  left: ReactNode[];
  right: ReactNode[];
  /** Vertical divider position as a fraction of width. */
  leftFraction?: number;
  className?: string;
}) {
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `minmax(0, ${leftFraction}fr) minmax(0, ${1 - leftFraction}fr)`,
  };
  const dashed = "border-dashed [border-color:var(--board-line)]";

  const column = (sections: ReactNode[], side: "left" | "right") =>
    sections.map((section, i) => {
      const last = i === sections.length - 1;
      return (
        <BoardCell
          key={i}
          padded={false}
          className={cn(
            dashed,
            last ? "flex-1" : "shrink-0 border-b",
            last && side === "left" && "border-b lg:border-b-0"
          )}
          markers={
            last ? undefined : side === "left" ? (
              <>
                <BoardCrossMark className={LEFT_EDGE} />
                <BoardRingMark className={RIGHT_EDGE} />
              </>
            ) : (
              <>
                <BoardRingMark className={LEFT_EDGE} />
                <BoardCrossMark className={RIGHT_EDGE} />
              </>
            )
          }
        >
          {section}
        </BoardCell>
      );
    });

  return (
    <div
      className={cn("relative w-full lg:h-full lg:min-h-[720px]", className)}
    >
      <div className="flex flex-col lg:grid lg:h-full" style={gridStyle}>
        <div
          className={cn(
            "flex min-w-0 flex-col lg:min-h-0",
            dashed,
            "lg:border-r"
          )}
        >
          {column(left, "left")}
        </div>
        <div className="flex min-w-0 flex-col lg:min-h-0">
          {column(right, "right")}
        </div>
      </div>

      <BoardCrossMark
        className="top-0 -translate-x-1/2 -translate-y-1/2"
        style={{ left: `${leftFraction * 100}%` }}
      />
      <BoardCrossMark
        className="bottom-0 -translate-x-1/2 translate-y-1/2"
        style={{ left: `${leftFraction * 100}%` }}
      />
    </div>
  );
}
