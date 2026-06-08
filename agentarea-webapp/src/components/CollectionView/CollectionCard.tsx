"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { CollectionActions } from "./CollectionActions";
import { Tile } from "./meta";
import type { CollectionItem } from "./types";

export default function CollectionCard({ item }: { item: CollectionItem }) {
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
        "group relative cursor-pointer overflow-hidden rounded-[10px] border border-zinc-200 bg-background p-3.5",
        "transition-[border-color,box-shadow] duration-150",
        "hover:border-zinc-300 hover:shadow-[0_2px_10px_rgba(0,0,0,0.04)]",
        "dark:border-zinc-800 dark:hover:border-zinc-700 dark:hover:shadow-[0_2px_10px_rgba(0,0,0,0.3)]"
      )}
    >
      {/* top: icon + title (+ optional aside, e.g. a status dot) */}
      <div className="relative z-[1] mb-[9px] flex items-center gap-[9px]">
        {!item.hideIcon && (
          <Tile color={item.color} icon={item.icon} variant="card" />
        )}
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-foreground">
          {item.title}
        </span>
        {item.headerAside != null && (
          <span className="flex shrink-0 items-center">{item.headerAside}</span>
        )}
      </div>

      {/* description — fixed two-line clamp (omitted for compact cards) */}
      {!item.hideDescription && (
        <p className="relative z-[1] mb-3 line-clamp-2 h-[38px] text-[12.5px] leading-[1.5] text-muted-foreground">
          {item.description || ""}
        </p>
      )}

      {/* footer: custom node, or default badges. `meta` is row-only (it's the
          trailing column there); cards omit it so it can't collide with the
          bottom-right open-arrow — use `cardFooter` for card-specific content. */}
      {item.cardFooter != null ? (
        <div className="relative z-[1]">{item.cardFooter}</div>
      ) : (
      <div className="relative z-[1] flex items-center gap-2">
        {item.badges?.map((badge, i) =>
          badge.color ? (
            <span
              key={i}
              className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80"
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
              className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground"
            >
              {badge.icon && <badge.icon className="h-3 w-3" strokeWidth={1.7} />}
              {badge.label}
            </span>
          )
        )}
      </div>
      )}

      {/* hover quick actions — top-right */}
      {hasActions && (
        <span
          className={cn(
            "absolute right-2.5 top-2.5 z-[2] flex items-center gap-0.5 transition-opacity",
            menuOpen
              ? "opacity-100"
              : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100"
          )}
        >
          <CollectionActions
            actions={actions}
            menuOpen={menuOpen}
            onMenuOpenChange={setMenuOpen}
            buttonClassName="bg-background/80 backdrop-blur-sm"
          />
        </span>
      )}

      {/* brand: diagonal hatch — soft footer band that grows into a full wash on hover */}
      <span className="collection-card-hatch" aria-hidden />

      {/* brand: diagonal open-arrow, bottom-right */}
      <span className="pointer-events-none absolute bottom-[11px] right-[11px] z-[2] grid h-5 w-5 place-items-center text-muted-foreground/70 transition-[color,transform] duration-150 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary">
        <ArrowUpRight className="h-4 w-4" strokeWidth={2} />
      </span>
    </div>
  );
}
