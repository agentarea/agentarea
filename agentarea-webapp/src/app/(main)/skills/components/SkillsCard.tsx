"use client";

import type { MouseEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Copy, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/skill";
import { scopeMeta, SkillTile, sourceMeta } from "./skillsMeta";

interface SkillsCardProps {
  skill: Skill;
  isFavorite: boolean;
  onToggleFavorite: (id: string) => void;
}

export default function SkillsCard({
  skill,
  isFavorite,
  onToggleFavorite,
}: SkillsCardProps) {
  const router = useRouter();
  const source = sourceMeta(skill.source_type);
  const scope = scopeMeta(skill.network_scope);
  const SourceIcon = source.icon;
  const ScopeIcon = scope.icon;

  const open = () => router.push(`/skills/${skill.id}`);
  const stop = (e: MouseEvent) => e.stopPropagation();

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
        "group relative overflow-hidden cursor-pointer rounded-[10px] border border-zinc-200 bg-background p-3.5",
        "transition-[border-color,box-shadow] duration-150",
        "hover:border-zinc-300 hover:shadow-[0_2px_10px_rgba(0,0,0,0.04)]",
        "dark:border-zinc-800 dark:hover:border-zinc-700 dark:hover:shadow-[0_2px_10px_rgba(0,0,0,0.3)]"
      )}
    >
      {/* top: icon + name */}
      <div className="relative z-[1] mb-[9px] flex items-center gap-[9px]">
        <SkillTile color={source.color} icon={SourceIcon} variant="card" />
        <span className="truncate text-[13.5px] font-semibold text-foreground">
          {skill.name}
        </span>
      </div>

      {/* description — fixed two-line clamp */}
      <p className="relative z-[1] mb-3 line-clamp-2 h-[38px] text-[12.5px] leading-[1.5] text-muted-foreground">
        {skill.description || ""}
      </p>

      {/* footer: source label pill + network scope */}
      <div className="relative z-[1] flex items-center gap-2">
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
      </div>

      {/* hover quick actions — top-right. Hidden via opacity (not display) so
          the trigger keeps a valid layout box; otherwise Radix loses its
          anchor on mouse-leave and the menu jumps/flashes at 0,0 — including
          during the close animation. */}
      <span
        className={cn(
          "absolute right-2.5 top-2.5 z-[2] flex items-center gap-0.5 transition-opacity",
          "opacity-0 pointer-events-none group-hover:pointer-events-auto group-hover:opacity-100"
        )}
      >
        <button
          type="button"
          title="Favorite"
          onClick={(e) => {
            stop(e);
            onToggleFavorite(skill.id);
          }}
          className="grid h-[26px] w-[26px] place-items-center rounded-md bg-background/80 text-muted-foreground backdrop-blur-sm hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
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
          className="grid h-[26px] w-[26px] place-items-center rounded-md bg-background/80 text-muted-foreground backdrop-blur-sm hover:bg-zinc-200/70 hover:text-foreground dark:hover:bg-zinc-700"
        >
          <Copy className="h-[15px] w-[15px]" />
        </button>
      </span>

      {/* brand: diagonal hatch — soft footer band that grows into a full wash on hover */}
      <span className="skill-card-hatch" aria-hidden />

      {/* brand: diagonal open-arrow, bottom-right */}
      <span className="pointer-events-none absolute bottom-[11px] right-[11px] z-[2] grid h-5 w-5 place-items-center text-muted-foreground/70 transition-[color,transform] duration-150 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary">
        <ArrowUpRight className="h-4 w-4" strokeWidth={2} />
      </span>
    </div>
  );
}
