"use client";

import { useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";
import { ExternalLink, Hash, Clock } from "lucide-react";
import { Skill } from "@/lib/api";
import {
  InfoPanelExpandableText,
  InfoPanelField,
  InfoPanelSection,
  InfoPanelValueBox,
} from "@/components/InfoPanel";

interface SkillDetailsProps {
  skill: Skill;
}

export default function SkillDetails({ skill }: SkillDetailsProps) {
  const tDetail = useTranslations("SkillsPage.detail");
  const t = useTranslations("SkillsPage");

  return (
    <InfoPanelSection title={tDetail("details")} contentClassName="space-y-3 text-xs">
      <div className="space-y-1">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {tDetail("name")}
        </div>
        <div className="text-sm font-semibold text-foreground">
          {skill.name}
        </div>
      </div>

      <div className="space-y-1">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {tDetail("description")}
        </div>
        {skill.description ? (
          <InfoPanelExpandableText
            content={skill.description}
            maxLines={3}
            textClassName="text-sm text-foreground"
          />
        ) : (
          <div className="text-sm text-foreground">-</div>
        )}
      </div>

      <InfoPanelField label={t("skillId")} icon={Hash}>
        <InfoPanelValueBox mono>{skill.id}</InfoPanelValueBox>
      </InfoPanelField>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Clock className="h-3 w-3 text-primary" />
          {tDetail("updated")}
        </div>
        <div className="text-[13px] font-medium text-foreground">
          {formatDistanceToNow(new Date(skill.updated_at), { addSuffix: true })}
        </div>
      </div>

      {skill.source_url && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("sourceUrl")}
          </div>
          <a
            href={skill.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {skill.source_url} <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      )}
    </InfoPanelSection>
  );
}
