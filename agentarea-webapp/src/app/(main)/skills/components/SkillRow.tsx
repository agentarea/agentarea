"use client";

import { useRouter } from "next/navigation";
import { Copy, MoreHorizontal, Star } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/skill";
import { scopeMeta, shortAge, sourceMeta } from "./skillsMeta";

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
        "group relative flex h-10 cursor-pointer items-center gap-3 px-4",
        "border-b border-zinc-100 dark:border-zinc-800/70",
        "hover:bg-muted/60 dark:hover:bg-zinc-800/50"
      )}
    >
      {/* leading glyph */}
      <span
        className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] text-white"
        style={{ backgroundColor: source.color }}
      >
        <SourceIcon className="h-3 w-3" strokeWidth={2.2} />
      </span>

      {/* name */}
      <span className="max-w-[230px] shrink-0 truncate text-[13px] font-medium text-foreground">
        {skill.name}
      </span>

      {/* description */}
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
        {skill.description || ""}
      </span>

      {/* meta cluster — hidden while hovering to make room for quick actions */}
      <span className="flex shrink-0 items-center gap-2 group-hover:invisible">
        <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80">
          <span
            className="h-[7px] w-[7px] rounded-full"
            style={{ backgroundColor: source.color }}
          />
          {source.label}
        </span>
        <span className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <ScopeIcon className="h-3 w-3" strokeWidth={1.7} />
          {scope.label}
        </span>
        <span className="w-12 text-right text-[11.5px] text-muted-foreground/80">
          {shortAge(skill.created_at)}
        </span>
      </span>

      {/* hover quick actions */}
      <span className="absolute right-3 hidden h-full items-center gap-0.5 pl-8 group-hover:flex bg-gradient-to-l from-muted/60 via-muted/60 to-transparent dark:from-zinc-800/50 dark:via-zinc-800/50">
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
        <DropdownMenu>
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
    </div>
  );
}
