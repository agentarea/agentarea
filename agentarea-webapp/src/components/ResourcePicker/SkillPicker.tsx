"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { SkillResponse } from "@/api/client/types.gen";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { skillDisplay } from "@/lib/skill-display";
import { ResourcePicker } from "./ResourcePicker";

const SkillIcon = ENTITY_ICONS.skill;

/** Pick skills to attach, sharing the loading, error and empty states. */
export function SkillPicker({
  title,
  description,
  resources,
  selectedIds,
  onAdd,
  onRemove,
}: {
  title: ReactNode;
  description: ReactNode;
  resources: AttachableResources;
  selectedIds: string[];
  onAdd: (skill: SkillResponse) => void;
  onRemove: (skill: SkillResponse) => void;
}) {
  const t = useTranslations("Pickers");
  const { skills, loading, failed, refresh } = resources;

  return (
    <ResourcePicker
      title={title}
      description={description}
      items={skills}
      selectedIds={selectedIds}
      onAdd={onAdd}
      onRemove={onRemove}
      loading={loading}
      failed={failed.includes("skills")}
      onRefresh={refresh}
      iconsType="skills"
      emptyTitle={t("emptySkillsTitle")}
      emptyHint={t("emptySkillsHint")}
      createText={t("manageSkills")}
      createHref="/skills/create"
      manageText={t("manageSkillsLink")}
      manageHref="/skills"
      heading={t("skillsHeading")}
      extractTitle={(skill) => skillDisplay(skill).title}
      extractSubtitle={(skill) => {
        const { subtitle, ref } = skillDisplay(skill);
        return [subtitle, ref].filter(Boolean).join(" · ") || null;
      }}
      extractIcon={() => <SkillIcon strokeWidth={1.85} />}
    />
  );
}
