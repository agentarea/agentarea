"use client";

import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Copy, Star } from "lucide-react";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
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
  const router = useWorkspaceRouter();
  const t = useTranslations("SkillsPage");
  const source = sourceMeta(skill.source_type);
  const scope = scopeMeta(skill.network_scope);
  const SourceIcon = source.icon;
  const ScopeIcon = scope.icon;

  const open = () => router.push(`/skills/${skill.id}`);

  return (
    <InteractiveListRow
      onClick={open}
      start={<SkillTile skillId={skill.id} variant="row" />}
      contentClassName="gap-3"
      end={
        <>
          <span className="skill-col-source inline-flex h-[22px] items-center gap-1.5 rounded-full border border-border bg-background px-2 text-[11.5px] font-normal text-foreground/80">
            <SourceIcon className="h-3 w-3" strokeWidth={1.7} />
            {source.label}
          </span>
          <span className="skill-col-scope inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
            <ScopeIcon className="h-3 w-3" strokeWidth={1.7} />
            {scope.label}
          </span>
          <span className="skill-col-date w-12 text-right text-[11.5px] text-muted-foreground">
            {shortAge(skill.created_at)}
          </span>
        </>
      }
      hoverActionsClassName="bg-gradient-to-l from-muted/60 via-muted/60 to-transparent dark:from-zinc-800/50 dark:via-zinc-800/50"
      hoverActions={
        <>
          <button
            type="button"
            title={t("rowActions.favorite")}
            aria-label={t("rowActions.favorite")}
            aria-pressed={isFavorite}
            onClick={() => onToggleFavorite(skill.id)}
            className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-700 max-[767px]:h-11 max-[767px]:w-11"
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
            className="grid h-[26px] w-[26px] place-items-center rounded-md text-muted-foreground hover:bg-zinc-200/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-700 max-[767px]:h-11 max-[767px]:w-11"
          >
            <Copy className="h-[15px] w-[15px]" />
          </button>
        </>
      }
    >
      <>
        <span className="max-w-[230px] shrink-0 truncate text-[13px] font-medium text-foreground max-[767px]:max-w-[130px] max-[767px]:shrink">
          {skill.name}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
          {skill.description || ""}
        </span>
      </>
    </InteractiveListRow>
  );
}
