"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
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
  const router = useWorkspaceRouter();
  const skillNameId = useId();
  const t = useTranslations("SkillsPage");
  const source = sourceMeta(skill.source_type);
  const scope = scopeMeta(skill.network_scope);
  const SourceIcon = source.icon;
  const ScopeIcon = scope.icon;

  return (
    <div
      className={cn(
        "group relative cursor-pointer overflow-hidden rounded-[10px] border border-zinc-200 bg-background p-3.5",
        "transition-[border-color,box-shadow] duration-150 motion-reduce:transition-none",
        "hover:border-zinc-300 hover:shadow-[0_2px_10px_rgba(0,0,0,0.04)]",
        "dark:border-zinc-800 dark:hover:border-zinc-700 dark:hover:shadow-[0_2px_10px_rgba(0,0,0,0.3)]"
      )}
    >
      <WorkspaceLink
        href={`/skills/${skill.id}`}
        aria-labelledby={skillNameId}
        className="absolute inset-0 z-0 rounded-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      />
      {/* top: icon + name */}
      <div className="pointer-events-none relative z-[1] mb-[9px] flex items-center gap-[9px] md:group-hover:pr-16 md:group-focus-within:pr-16 max-[767px]:pr-24">
        <SkillTile skillId={skill.id} variant="card" />
        <span
          id={skillNameId}
          aria-hidden
          className="truncate text-[13.5px] font-semibold text-foreground"
        >
          {skill.name}
        </span>
      </div>

      {/* description — fixed two-line clamp */}
      <p className="pointer-events-none relative z-[1] mb-3 h-[38px] line-clamp-2 text-[12.5px] leading-[1.5] text-muted-foreground">
        {skill.description || ""}
      </p>

      {/* footer: source label pill + network scope */}
      <div className="pointer-events-none relative z-[1] flex items-center gap-2">
        <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80">
          <SourceIcon className="h-3 w-3" strokeWidth={1.7} />
          {source.label}
        </span>
        <span className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <ScopeIcon className="h-3 w-3" strokeWidth={1.7} />
          {scope.label}
        </span>
      </div>

      {/* Hidden actions become available on hover, keyboard focus, and touch. */}
      <span
        className={cn(
          "absolute right-2.5 top-2.5 z-[2] flex items-center gap-0.5 transition-opacity motion-reduce:transition-none",
          "invisible pointer-events-none opacity-0 group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:visible group-focus-within:pointer-events-auto group-focus-within:opacity-100 max-[767px]:visible max-[767px]:pointer-events-auto max-[767px]:opacity-100 [@media(hover:none)]:visible [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100"
        )}
      >
        <button
          type="button"
          title={t("rowActions.favorite")}
          aria-label={t("rowActions.favorite")}
          aria-pressed={isFavorite}
          onClick={() => onToggleFavorite(skill.id)}
          className="grid h-[26px] w-[26px] place-items-center rounded-md bg-background/80 text-muted-foreground backdrop-blur-sm hover:bg-zinc-200/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-700 max-[767px]:h-11 max-[767px]:w-11"
        >
          <Star
            className="h-[15px] w-[15px]"
            fill={isFavorite ? "currentColor" : "none"}
            style={isFavorite ? { color: "#d99a00" } : undefined}
          />
        </button>
        <button
          type="button"
          title={t("rowActions.duplicate")}
          aria-label={t("rowActions.duplicate")}
          onClick={() => router.push(`/skills/create?from=${skill.id}`)}
          className="grid h-[26px] w-[26px] place-items-center rounded-md bg-background/80 text-muted-foreground backdrop-blur-sm hover:bg-zinc-200/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-700 max-[767px]:h-11 max-[767px]:w-11"
        >
          <Copy className="h-[15px] w-[15px]" />
        </button>
      </span>

      <span className="skill-card-hatch pointer-events-none" aria-hidden />

      {/* brand: diagonal open-arrow, bottom-right */}
      <span className="pointer-events-none absolute bottom-[11px] right-[11px] z-[2] grid h-5 w-5 place-items-center text-muted-foreground/70 transition-[color,transform] duration-150 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary motion-reduce:transition-none">
        <ArrowUpRight className="h-4 w-4" strokeWidth={2} />
      </span>
    </div>
  );
}
