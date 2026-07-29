"use client";

import React from "react";
import Image from "next/image";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { AgentAvatar } from "@/components/AgentAvatar";

export interface Agent {
  id: string;
  name: string;
  avatar?: string;
}

interface MentionMenuProps {
  show: boolean;
  agents: Agent[];
  position: { top: number; left: number; width: number; side: 'top' | 'bottom' };
  selectedIndex: number;
  menuRef: React.RefObject<HTMLDivElement | null>;
  onAgentSelect: (agent: Agent) => void;
}

export function MentionMenu({
  show,
  agents,
  position,
  selectedIndex,
  menuRef,
  onAgentSelect,
}: MentionMenuProps) {
  if (!show || agents.length === 0) {
    return null;
  }

  return (
    <div
      ref={menuRef}
      className="fixed z-[100] border-x border-t border-b rounded-sm"
      style={{
        top: `${position.top}px`,
        left: `${position.left}px`,
        width: `${position.width}px`,
        minWidth: `${position.width}px`,
        maxWidth: `${position.width}px`,
      }}
    >
      <Command shouldFilter={false} className="rounded-none">
        <CommandList className="max-h-48">
          <CommandEmpty className="py-1.5 px-2 text-xs text-muted-foreground">
            No agents found.
          </CommandEmpty>
          <CommandGroup className="p-0 [&>*:first-child]:rounded-t-none [&>*:last-child]:rounded-b-none">
            {agents.map((agent, index) => (
              <CommandItem
                key={agent.id}
                value={agent.id}
                onSelect={() => onAgentSelect(agent)}
                className={cn(
                  "rounded-none",
                  index === selectedIndex && selectedIndex >= 0 ? "bg-accent/50" : ""
                )}
              >
                {agent.avatar ? (
                  <Image
                    src={agent.avatar}
                    alt={agent.name}
                    width={24}
                    height={24}
                    className="h-6 w-6 rounded-full object-cover flex-shrink-0"
                  />
                ) : (
                  <AgentAvatar agent={agent} size="sm" />
                )}
                <span className="text-xs font-medium truncate">{agent.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}

