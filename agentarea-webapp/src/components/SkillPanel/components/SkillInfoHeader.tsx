"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Skill } from "@/lib/browser-api";
import { InfoPanelHeader } from "@/components/InfoPanel";

interface SkillInfoHeaderProps {
  skill: Skill;
}

export default function SkillInfoHeader({ skill }: SkillInfoHeaderProps) {
  const t = useTranslations("SkillsPage");
  const tSource = useTranslations("SkillsPage.source");
  const statusVariant = "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200";

  return (
    <InfoPanelHeader
      label={t("skill")}
      title={skill.name || t("untitledSkill")}
      right={
        <Badge
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusVariant}`}
        >
          {tSource(skill.source_type)}
        </Badge>
      }
    />
  );
}
