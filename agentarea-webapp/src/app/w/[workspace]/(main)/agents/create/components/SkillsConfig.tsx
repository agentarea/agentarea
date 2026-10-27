import React, { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";
import AccordionControl from "@/components/AccordionControl";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  SkillPickerPanel,
  skillSubtitle,
  useSkillSearch,
} from "@/components/ResourcePicker/SkillPickerPanel";
import SearchInput from "@/components/SearchInput/SearchInput";
import { Accordion } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import Note from "@/components/ui/note";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { skillDisplay } from "@/lib/skill-display";
import type { AgentSkill } from "../types";

const SkillIcon = ENTITY_ICONS.skill;

type SkillsConfigProps = {
  selectedSkills: AgentSkill[];
  onSkillsChange: (skills: AgentSkill[]) => void;
};

const SkillsConfig = ({
  selectedSkills,
  onSkillsChange,
}: SkillsConfigProps) => {
  const t = useTranslations("AgentsPage.create.skills");
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
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={SkillIcon} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={<p>{t("note")}</p>}
      mainControl={
        <ConfigSheet
          title={t("title")}
          description={t("description")}
          triggerText={t("trigger")}
          className="ml-auto"
          open={isSheetOpen}
          onOpenChange={handleSheetOpenChange}
        >
          <SkillsSheetBody
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
      <div className="space-y-4">
        {selectedSkills.length > 0 && (
          <div className="space-y-2">
            <Accordion type="multiple" id="skills-items" className="space-y-2">
              {selectedSkills.map((skill, index) => {
                // The workspace's copy carries the source URL the repo line is
                // read from; the agent's has only name and description.
                const display = skillDisplay(
                  resources.skills.find((s) => s.id === skill.id) ?? skill
                );
                const subtitle = skillSubtitle(display);
                return (
                  <CardAccordionItem
                    key={`skill-${skill.id}`}
                    value={`skill-${index}`}
                    hideChevron
                    title={
                      <div className="flex min-w-0 flex-row items-center gap-2 px-[7px] py-[7px]">
                        <SkillIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-medium">
                            {display.title}
                          </h3>
                          {subtitle ? (
                            <p className="truncate text-xs text-muted-foreground">
                              {subtitle}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    }
                    controls={
                      <div className="flex flex-row items-center gap-3">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => handleRemoveSkill(skill.id)}
                          className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                          aria-label={t("remove")}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    }
                  />
                );
              })}
            </Accordion>
          </div>
        )}

        {selectedSkills.length === 0 && (
          <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground">
            <p>{t("empty")}</p>
          </Note>
        )}
      </div>
    </AccordionControl>
  );
};

/** Mounted only while the sheet is open, so each opening starts a fresh search. */
function SkillsSheetBody(
  props: Omit<React.ComponentProps<typeof SkillPickerPanel>, "search">
) {
  const tCommon = useTranslations("Common");
  const search = useSkillSearch();
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <SearchInput
        delay={150}
        onDebouncedChange={search.setQuery}
        placeholder={tCommon("search")}
      />
      <div className="-mx-6 min-h-0 flex-1 overflow-y-auto px-1 py-2">
        <SkillPickerPanel {...props} search={search} />
      </div>
    </div>
  );
}

export default SkillsConfig;
