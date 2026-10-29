"use client";

import React, { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import AccordionControl from "@/components/AccordionControl";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { PickerPanel } from "@/components/ResourcePicker/PickerPanel";
import {
  SkillPickerPanel,
  skillSubtitle,
  useSkillSearch,
} from "@/components/ResourcePicker/SkillPickerPanel";
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
  // A skill installed from the catalog is not in `resources` until it reloads.
  const installedFromCatalog = useRef(false);

  const handleAddSkill = (skill: AgentSkill) => {
    if (selectedSkills.some((s) => s.id === skill.id)) return;
    if (!resources.skills.some((s) => s.id === skill.id)) {
      installedFromCatalog.current = true;
    }
    onSkillsChange([...selectedSkills, skill]);
  };

  const handleRemoveSkill = (skillId: string) => {
    onSkillsChange(selectedSkills.filter((s) => s.id !== skillId));
  };

  const handleSheetOpenChange = (open: boolean) => {
    setIsSheetOpen(open);
    if (!open && installedFromCatalog.current) {
      installedFromCatalog.current = false;
      resources.refresh();
    }
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
          onOpenChange={handleSheetOpenChange}
          panel
        >
          <SkillsSheetBody
            title={t("title")}
            description={t("sheetDescription")}
            resources={resources}
            selectedIds={selectedSkills.map((s) => s.id)}
            onAdd={(skill) =>
              handleAddSkill({
                id: skill.id,
                name: skill.name,
                description: skill.description,
              })
            }
            onRemove={handleRemoveSkill}
          />
        </ConfigSheet>
      }
    >
      <SelectedItems count={selectedSkills.length} empty={t("empty")}>
        {selectedSkills.map((skill) => {
          // The workspace's copy carries the source URL the repo line is
          // read from; the agent's has only name and description.
          const display = skillDisplay(
            resources.skills.find((s) => s.id === skill.id) ?? skill
          );
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
              title={display.title}
              subtitle={skillSubtitle(display)}
              removeLabel={t("remove", { name: display.title })}
              onRemove={() => handleRemoveSkill(skill.id)}
            />
          );
        })}
      </SelectedItems>
    </AccordionControl>
  );
};

/**
 * The sheet's frame around the skills list; mounted only while the sheet is
 * open, so each opening starts a fresh catalog search.
 */
function SkillsSheetBody({
  title,
  description,
  ...props
}: Omit<React.ComponentProps<typeof SkillPickerPanel>, "search"> & {
  title: string;
  description: string;
}) {
  const tPickers = useTranslations("Pickers");
  const search = useSkillSearch();
  return (
    <PickerPanel
      title={title}
      description={description}
      onSearch={search.setQuery}
      manageText={tPickers("manageSkillsLink")}
      manageHref="/skills"
    >
      <SkillPickerPanel {...props} search={search} />
    </PickerPanel>
  );
}

export default SkillsConfig;
