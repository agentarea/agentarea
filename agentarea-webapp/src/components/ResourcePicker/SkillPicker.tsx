"use client";

import { useTranslations } from "next-intl";
import type { SkillResponse } from "@/api/client/types.gen";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { ResourcePicker } from "./ResourcePicker";

const SkillIcon = ENTITY_ICONS.skill;

/** Pick skills to attach, sharing the loading, error and empty states. */
export function SkillPicker({
  resources,
  selectedIds,
  onAdd,
  onRemove,
}: {
  resources: AttachableResources;
  selectedIds: string[];
  onAdd: (skill: SkillResponse) => void;
  onRemove: (skill: SkillResponse) => void;
}) {
  const t = useTranslations("Pickers");
  const { skills, loading, failed, refresh } = resources;

  return (
    <ResourcePicker
      items={skills}
      prefix="skill"
      selectedIds={selectedIds}
      onAdd={onAdd}
      onRemove={onRemove}
      loading={loading}
      failed={failed.includes("skills")}
      onRefresh={refresh}
      emptyText={t("noSkills")}
      manageText={t("manageSkills")}
      manageHref="/skills/create"
      extractTitle={(skill) => (
        <span className="flex items-center gap-2">
          <SkillIcon className="h-4 w-4" />
          {skill.name}
        </span>
      )}
    />
  );
}
