"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Skill } from "@/lib/browser-api";

interface SkillInfoHeaderProps {
  skill: Skill;
}

export default function SkillInfoHeader({ skill }: SkillInfoHeaderProps) {
  const t = useTranslations("SkillsPage");
  const tSource = useTranslations("SkillsPage.source");
  const statusVariant = "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200";

  return (
    <div className="flex items-start justify-between gap-3 px-3 pb-3 pt-3">
      <div className="space-y-1">
        <div className="text-xs uppercase tracking-wide text-muted-foreground font-normal">
          {t("skill")}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {skill.name || t("untitledSkill")}
        </h3>
      </div>
      <Badge
        className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusVariant}`}
      >
        {tSource(skill.source_type)}
      </Badge>
    </div>
  );
}
