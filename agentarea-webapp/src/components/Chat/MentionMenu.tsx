"use client";

import React, { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { AgentAvatar } from "@/components/AgentAvatar";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import { cn } from "@/lib/utils";

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
}

interface MentionMenuProps {
  show: boolean;
  agents: Agent[];
  position: { top: number; left: number; width: number; side: 'top' | 'bottom' };
  selectedIndex: number;
  menuRef: React.RefObject<HTMLDivElement | null>;
  onAgentSelect: (agent: Agent) => void;
}

/** Narrower than the composer: a picker for a name, not a second panel. */
const MAX_WIDTH = 320;

/** Air between the menu and the composer edge it opens from. */
const GAP = 6;

/**
 * The @ menu. Dressed like the composer's own agent and policy dropdowns
 * (ContextSelect) — same card, rows and avatars — so it reads as one of them
 * rather than as a strip glued to the textarea.
 *
 * Selection is driven by the textarea (arrow keys go through useMentions), so
 * rows never take focus: mousedown is cancelled and the caret stays put.
 */
export function MentionMenu({
  show,
  agents,
  position,
  selectedIndex,
  menuRef,
  onAgentSelect,
}: MentionMenuProps) {
  const t = useTranslations("Chat.inputControls");
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep the row picked with the arrow keys in view in a long list.
  useEffect(() => {
    itemRefs.current[selectedIndex]?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!show || agents.length === 0) {
    return null;
  }

  return (
    <div
      ref={menuRef}
      role="listbox"
      aria-label={t("mentionHeading")}
      className={cn(
        "fixed z-[100] overflow-hidden rounded-md border border-zinc-200/90 bg-white p-1 text-zinc-900",
        "shadow-[0_12px_32px_rgba(15,23,42,0.10),0_2px_6px_rgba(15,23,42,0.04)]",
        "dark:border-zinc-800 dark:bg-zinc-950/95 dark:text-zinc-100"
      )}
      style={{
        top: `${position.top}px`,
        left: `${position.left}px`,
        width: `${Math.min(position.width, MAX_WIDTH)}px`,
        transform: `translateY(${position.side === "top" ? -GAP : GAP}px)`,
      }}
    >
      <MenuSectionLabel>{t("mentionHeading")}</MenuSectionLabel>
      <div className="max-h-56 overflow-y-auto">
        {agents.map((agent, index) => {
          const active = index === selectedIndex;
          return (
            <button
              key={agent.id}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              type="button"
              role="option"
              aria-selected={active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onAgentSelect(agent)}
              className={cn(
                "flex min-h-8 w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px] text-zinc-800 transition-colors",
                "hover:bg-zinc-100/90 dark:text-zinc-100 dark:hover:bg-zinc-900",
                active && "bg-zinc-100/90 dark:bg-zinc-900"
              )}
            >
              <AgentAvatar agent={agent} size="xs" className="shrink-0" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate leading-4">{agent.name}</span>
                {agent.description ? (
                  <span className="truncate pt-0.5 text-[11px] leading-4 text-zinc-500 dark:text-zinc-400">
                    {agent.description}
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
