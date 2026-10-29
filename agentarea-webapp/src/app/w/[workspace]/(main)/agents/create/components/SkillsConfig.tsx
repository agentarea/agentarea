"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import AccordionControl from "@/components/AccordionControl";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SkillPicker } from "@/components/ResourcePicker/SkillPicker";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { skillDisplay } from "@/lib/skill-display";
import type { AgentSkill } from "../types";
import { SelectedItemRow, SelectedItems } from "./SelectedItemRow";

const SkillIcon = ENTITY_ICONS.skill;

type SkillsConfigProps = {
  selectedSkills: AgentSkill[];
  onSkillsChange: (skills: AgentSkill[]) => void;
};

const SkillsConfig = ({
  selectedSkills,
  onSkillsChange,
}: SkillsConfigProps) => {
  const t = useTranslations("AgentsPage.skillsConfig");
  const [accordionValue, setAccordionValue] = useState<string>("skills");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const resources = useAttachableResources();

  const handleAddSkill = (skill: AgentSkill) => {
    if (selectedSkills.some((s) => s.id === skill.id)) return;
    onSkillsChange([...selectedSkills, skill]);
  };

  const handleRemoveSkill = (skillId: string) => {
    onSkillsChange(selectedSkills.filter((s) => s.id !== skillId));
  };

  return (
    <AccordionControl
      id="skills"
      count={selectedSkills.length}
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={SkillIcon} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      noteInline
      note={t("note")}
      mainControl={
        <ConfigSheet
          title={t("title")}
          description={t("sheetDescription")}
          triggerText={t("add")}
          className="ml-auto"
          triggerVariant="primaryOutline"
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
          panel
        >
          <SkillPicker
            title={t("title")}
            description={t("sheetDescription")}
            resources={resources}
            selectedIds={selectedSkills.map((s) => s.id)}
            onAdd={(skill) => handleAddSkill(skill as AgentSkill)}
            onRemove={(skill) => handleRemoveSkill(skill.id)}
          />
        </ConfigSheet>
      }
    >
      <SelectedItems count={selectedSkills.length} empty={t("empty")}>
        {selectedSkills.map((skill) => {
          const { title, subtitle } = skillDisplay(skill);
          return (
            <SelectedItemRow
              key={skill.id}
              avatar={
                <EntityAvatar
                  hue={deterministicHue(skill.id)}
                  size={24}
                  iconScale={0.45}
                  icon={<SkillIcon strokeWidth={1.85} />}
                  aria-hidden
                />
              }
              title={title}
              subtitle={subtitle}
              removeLabel={t("remove", { name: title })}
              onRemove={() => handleRemoveSkill(skill.id)}
            />
          );
        })}
      </SelectedItems>
    </AccordionControl>
  );
};

export default SkillsConfig;
