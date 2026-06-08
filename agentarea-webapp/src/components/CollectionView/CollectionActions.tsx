"use client";

import { MoreHorizontal } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { CollectionAction } from "./types";

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * Hover quick-action cluster shared by rows and cards: the first few actions
 * render as icon buttons; an overflow ⋯ menu appears only when there are
 * menu-only actions or more actions than fit as buttons.
 */
export function CollectionActions({
  actions,
  menuOpen,
  onMenuOpenChange,
  maxButtons = 3,
  buttonClassName,
}: {
  actions: CollectionAction[];
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  maxButtons?: number;
  buttonClassName?: string;
}) {
  const buttonActions = actions.filter((a) => !a.menuOnly).slice(0, maxButtons);
  const overflow =
    actions.length > buttonActions.length ||
    actions.some((a) => a.menuOnly);

  const btn = cn(
    "grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700",
    buttonClassName
  );

  return (
    <>
      {buttonActions.map((action) => (
        <button
          key={action.label}
          type="button"
          title={action.label}
          aria-label={action.label}
          onClick={(e) => {
            stop(e);
            action.onClick(e);
          }}
          className={btn}
        >
          <action.icon
            className="h-[15px] w-[15px]"
            fill={action.active ? "currentColor" : "none"}
            style={action.active && action.activeColor ? { color: action.activeColor } : undefined}
          />
        </button>
      ))}
      {overflow && (
        <DropdownMenu open={menuOpen} onOpenChange={onMenuOpenChange}>
          <DropdownMenuTrigger asChild onClick={stop}>
            <button type="button" title="More" aria-label="More" className={btn}>
              <MoreHorizontal className="h-[15px] w-[15px]" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" onClick={stop}>
            {actions.map((action) => (
              <DropdownMenuItem
                key={action.label}
                onSelect={() => action.onClick({ stopPropagation() {} } as React.MouseEvent)}
              >
                <action.icon className="mr-2 h-3.5 w-3.5" />
                {action.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </>
  );
}
