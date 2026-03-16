"use client";

import { useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";
import { ExternalLink, Hash, Clock } from "lucide-react";
import { Skill } from "@/lib/browser-api";
import ExpandableText from "@/components/TaskInfoPanel/components/ExpandableText";
import Section from "@/components/TaskInfoPanel/components/Section";

interface SkillDetailsProps {
  skill: Skill;
}

export default function SkillDetails({ skill }: SkillDetailsProps) {
  const tDetail = useTranslations("SkillsPage.detail");
  const t = useTranslations("SkillsPage");

  return (
    <Section title={tDetail("details")} contentClassName="space-y-3 text-xs">
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
          <ExpandableText
            content={skill.description}
            maxLines={3}
            textClassName="text-sm text-foreground"
          />
        ) : (
          <div className="text-sm text-foreground">-</div>
        )}
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Hash className="h-3 w-3 text-primary" />
          {t("skillId")}
        </div>
        <div className="truncate font-mono text-xs text-foreground bg-muted/30 p-1.5 rounded-md border border-border/50">
          {skill.id}
        </div>
      </div>

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
    </Section>
  );
}
