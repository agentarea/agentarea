"use client";

import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { Badge } from "@/components/ui/badge";
import { Skill } from "@/lib/api";

interface SkillInfoHeaderProps {
  skill: Skill;
}

export default function SkillInfoHeader({ skill }: SkillInfoHeaderProps) {
  const t = useTranslations("SkillsPage");
  const tDetail = useTranslations("SkillsPage.detail");
  const tSource = useTranslations("SkillsPage.source");
  const statusVariant =
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200";
  const catalogVariant =
    "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200";

  return (
    <InfoPanelHeader
      label={t("skill")}
      title={skill.name || t("untitledSkill")}
      right={
        <div className="flex flex-wrap justify-end gap-1.5">
          {skill.is_catalog && (
            <Badge
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${catalogVariant}`}
            >
              {tDetail("catalogTemplate")}
            </Badge>
          )}
          <Badge
            className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusVariant}`}
          >
            {tSource(skill.source_type)}
          </Badge>
        </div>
      }
    />
  );
}
