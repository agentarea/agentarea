"use client";

import { isValidElement, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { CollectionActions } from "./CollectionActions";
import { Tile } from "./meta";
import type { CollectionItem } from "./types";

/** Responsive column-drop classes, applied by badge position. The meta node
 *  (e.g. a date) drops first, then the secondary badge, then the primary. */
const BADGE_COL_CLASS = ["collection-col-source", "collection-col-scope"];

type RowCellObject = {
  node: ReactNode;
  colSpan?: number;
  className?: string;
  /** Keep this cell visible on hover (default: every cell after the first
   *  fades to make room for the open-arrow). */
  keepOnHover?: boolean;
};
type RowCell = ReactNode | RowCellObject;

function isCellObject(cell: RowCell): cell is RowCellObject {
  return (
    typeof cell === "object" &&
    cell !== null &&
    !isValidElement(cell) &&
    "node" in (cell as Record<string, unknown>)
  );
}

export default function CollectionRow({ item }: { item: CollectionItem }) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const actions = item.actions ?? [];
  const hasActions = actions.length > 0;

  const open = () => {
    if (item.onOpen) item.onOpen();
    else if (item.href) router.push(item.href);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      className={cn(
        "group relative flex h-10 cursor-pointer items-center gap-3 overflow-hidden px-4",
        "border-b border-zinc-100 dark:border-zinc-800/70",
        "hover:bg-muted/60 dark:hover:bg-zinc-800/50"
      )}
    >
      {/* brand: accent hatch softly slides in from the right edge on hover */}
      <span className="collection-row-hatch" aria-hidden />

      {/* leading glyph */}
      {!item.hideIcon && (
        <span className="relative z-[1] flex">
          <Tile
            color={item.color}
            icon={item.icon}
            variant="row"
            fill={item.iconFill}
          />
        </span>
      )}

      {/* grid mode: evenly-distributed columns laid out on `rowGrid`. The first
          column (name) stays put; the trailing columns hide on hover so the
          open-arrow has room — matching the default row's "title stays, meta
          hides" behaviour. */}
      {item.rowGrid || item.rowGridClassName ? (
        <div
          className={cn(
            "relative z-[1] grid min-w-0 flex-1 items-center gap-3",
            item.rowGridClassName
          )}
          style={item.rowGrid ? { gridTemplateColumns: item.rowGrid } : undefined}
        >
          {(item.rowCells ?? []).map((cell, i) => {
            const obj = isCellObject(cell);
            const node = obj ? cell.node : cell;
            const extra = obj ? cell.className : undefined;
            const span = obj ? cell.colSpan : undefined;
            // first cell (name) always stays; the rest fade on hover unless the
            // cell opts to keep itself visible (e.g. provider / description)
            const fades = i > 0 && !(obj && cell.keepOnHover);
            return (
              <div
                key={i}
                className={cn(
                  "flex min-w-0 items-center",
                  fades && "group-hover:invisible",
                  fades && menuOpen && "invisible",
                  extra
                )}
                style={span ? { gridColumn: `span ${span}` } : undefined}
              >
                {node}
              </div>
            );
          })}
        </div>
      ) : (
        <>
      {/* title — capped beside a description column, else fills the row */}
      <span
        className={cn(
          "relative z-[1] truncate text-[13px] font-medium text-foreground",
          item.titleClassName ??
            (item.description || item.rowMiddle
              ? "max-w-[230px] shrink-0"
              : "min-w-0 flex-1")
        )}
      >
        {item.title}
      </span>

      {/* inline pills after the title (e.g. Custom / Tools) */}
      {item.afterTitle != null && (
        <span className="relative z-[1] flex shrink-0 items-center gap-1.5">
          {item.afterTitle}
        </span>
      )}

      {/* flexible middle column: rich rowMiddle content takes priority over the
          plain description text (which still drives the card) */}
      {item.rowMiddle != null ? (
        <span className="relative z-[1] flex min-w-0 flex-1 items-center overflow-hidden">
          {item.rowMiddle}
        </span>
      ) : (
        item.description != null && (
          <span className="collection-subtext relative z-[1] min-w-0 flex-1 truncate">
            {item.description}
          </span>
        )
      )}

      {/* meta cluster — hidden on hover (or while the menu is open) to make room
          for the open-arrow + quick actions */}
      <span
        className={cn(
          "relative z-[1] flex shrink-0 items-center gap-2 group-hover:invisible",
          menuOpen && "invisible"
        )}
      >
        {item.badges?.map((badge, i) =>
          badge.color ? (
            <span
              key={i}
              className={cn(
                "inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80",
                BADGE_COL_CLASS[i]
              )}
            >
              <span
                className="h-[7px] w-[7px] rounded-full"
                style={{ backgroundColor: badge.color }}
              />
              {badge.label}
            </span>
          ) : (
            <span
              key={i}
              className={cn(
                "inline-flex items-center gap-1 text-[11.5px] text-muted-foreground",
                BADGE_COL_CLASS[i]
              )}
            >
              {badge.icon && <badge.icon className="h-3 w-3" strokeWidth={1.7} />}
              {badge.label}
            </span>
          )
        )}
        {item.meta != null &&
          (item.metaPlain ? (
            item.meta
          ) : (
            <span className="collection-col-date text-right text-[11.5px] text-muted-foreground/80">
              {item.meta}
            </span>
          ))}
      </span>
        </>
      )}

      {/* hover quick actions — hidden via opacity (not display) so the trigger
          keeps a valid layout box; otherwise Radix loses its anchor. */}
      {hasActions && (
        <span
          className={cn(
            "absolute right-10 z-[2] flex h-full items-center gap-0.5 bg-gradient-to-l from-muted/60 via-muted/60 to-transparent pl-8 transition-opacity dark:from-zinc-800/50 dark:via-zinc-800/50",
            menuOpen
              ? "opacity-100"
              : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100"
          )}
        >
          <CollectionActions
            actions={actions}
            menuOpen={menuOpen}
            onMenuOpenChange={setMenuOpen}
          />
        </span>
      )}

      {/* brand: diagonal open-arrow on row hover */}
      <span
        className={cn(
          "pointer-events-none absolute right-3 z-[2] hidden h-[22px] w-[22px] place-items-center text-primary",
          menuOpen ? "grid" : "group-hover:grid"
        )}
        aria-hidden
      >
        <ArrowUpRight className="h-4 w-4" strokeWidth={2} />
      </span>
    </div>
  );
}
