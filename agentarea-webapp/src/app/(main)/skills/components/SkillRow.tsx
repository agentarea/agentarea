"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Copy, MoreHorizontal, Star } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/skill";
import { scopeMeta, shortAge, SkillTile, sourceMeta } from "./skillsMeta";

interface SkillRowProps {
  skill: Skill;
  isFavorite: boolean;
  onToggleFavorite: (id: string) => void;
}

export default function SkillRow({
  skill,
  isFavorite,
  onToggleFavorite,
}: SkillRowProps) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const source = sourceMeta(skill.source_type);
  const scope = scopeMeta(skill.network_scope);
  const SourceIcon = source.icon;
  const ScopeIcon = scope.icon;

  const open = () => router.push(`/skills/${skill.id}`);

  const stop = (e: React.MouseEvent) => e.stopPropagation();

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
      <span className="skill-row-hatch" aria-hidden />

      {/* leading glyph */}
      <span className="relative z-[1] flex">
        <SkillTile color={source.color} icon={SourceIcon} variant="row" />
      </span>

      {/* name */}
      <span className="relative z-[1] max-w-[230px] shrink-0 truncate text-[13px] font-medium text-foreground">
        {skill.name}
      </span>

      {/* description */}
      <span className="relative z-[1] min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
        {skill.description || ""}
      </span>

      {/* meta cluster — hidden while hovering (or while the menu is open) to
          make room for quick actions */}
      <span
        className={cn(
          "relative z-[1] flex shrink-0 items-center gap-2 group-hover:invisible",
          menuOpen && "invisible"
        )}
      >
        <span className="skill-col-source inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80">
          <span
            className="h-[7px] w-[7px] rounded-full"
            style={{ backgroundColor: source.color }}
          />
          {source.label}
        </span>
        <span className="skill-col-scope inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <ScopeIcon className="h-3 w-3" strokeWidth={1.7} />
          {scope.label}
        </span>
        <span className="skill-col-date w-12 text-right text-[11.5px] text-muted-foreground/80">
          {shortAge(skill.created_at)}
        </span>
      </span>

      {/* hover quick actions — hidden via opacity (not display) so the trigger
          keeps a valid layout box; otherwise Radix loses its anchor on
          mouse-leave and the menu jumps/flashes at the corner — including
          during the close animation. */}
      <span
        className={cn(
          "absolute right-10 z-[2] flex h-full items-center gap-0.5 pl-8 bg-gradient-to-l from-muted/60 via-muted/60 to-transparent transition-opacity dark:from-zinc-800/50 dark:via-zinc-800/50",
          menuOpen
            ? "opacity-100"
            : "opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto"
        )}
      >
        <button
          type="button"
          title="Favorite"
          onClick={(e) => {
            stop(e);
            onToggleFavorite(skill.id);
          }}
          className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
        >
          <Star
            className="h-[15px] w-[15px]"
            fill={isFavorite ? "currentColor" : "none"}
            style={isFavorite ? { color: "#d99a00" } : undefined}
          />
        </button>
        <button
          type="button"
          title="Duplicate"
          onClick={(e) => {
            stop(e);
            router.push(`/skills/create?from=${skill.id}`);
          }}
          className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
        >
          <Copy className="h-[15px] w-[15px]" />
        </button>
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild onClick={stop}>
            <button
              type="button"
              title="More"
              className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
            >
              <MoreHorizontal className="h-[15px] w-[15px]" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" onClick={stop}>
            <DropdownMenuItem
              onSelect={() => router.push(`/skills/${skill.id}`)}
            >
              Open skill
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onToggleFavorite(skill.id)}>
              {isFavorite ? "Remove favorite" : "Add to favorites"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </span>

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
