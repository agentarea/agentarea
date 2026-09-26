import React, { useMemo, useState } from "react";
import { Sparkles, Trash2 } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Accordion } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import Note from "@/components/ui/note";
import type { AgentSkill } from "../types";
import AccordionControl from "@/components/AccordionControl";
import ConfigSheet from "@/components/ConfigSheet";
import { SkillPicker } from "@/components/ResourcePicker/SkillPicker";
import { useAttachableResources } from "@/hooks/use-attachable-resources";

type SkillsConfigProps = {
  selectedSkills: AgentSkill[];
  onSkillsChange: (skills: AgentSkill[]) => void;
};

const SkillsConfig = ({
  selectedSkills,
  onSkillsChange,
}: SkillsConfigProps) => {
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

  const note = useMemo(
    () => (
      <>
        <p>Skills extend agent capabilities with specialized behaviors and knowledge.</p>
      </>
    ),
    []
  );

  const title = useMemo(
    () => (
      <FormLabel icon={Sparkles} className="cursor-pointer">
        Skills
      </FormLabel>
    ),
    []
  );

  return (
    <AccordionControl
      id="skills"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={title}
      note={note}
      mainControl={
        <ConfigSheet
          title="Skills"
          description="Add skills to enhance your agent's capabilities"
          triggerText="Skill"
          className="ml-auto"
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
        >
          <div className="flex flex-col space-y-4 overflow-y-auto">
            <div className="flex items-center gap-2 font-semibold text-sm">
              <Sparkles className="h-4 w-4 text-muted-foreground" />
              Available Skills
            </div>
            <SkillPicker
              resources={resources}
              selectedIds={selectedSkills.map((s) => s.id)}
              onAdd={(skill) => handleAddSkill(skill as AgentSkill)}
              onRemove={(skill) => handleRemoveSkill(skill.id)}
            />
          </div>
        </ConfigSheet>
      }
    >
      <div className="space-y-4">
        {/* Selected Skills */}
        {selectedSkills.length > 0 && (
          <div className="space-y-2">
            <Accordion
              type="multiple"
              id="skills-items"
              className="space-y-2"
            >
              {selectedSkills.map((skill, index) => (
                <CardAccordionItem
                  key={`skill-${skill.id}`}
                  value={`skill-${index}`}
                  title={
                    <div className="flex flex-row items-center gap-1 px-[7px] py-[7px]">
                      <Sparkles className="h-4 w-4 text-muted-foreground" />
                      <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
                        {skill.name}
                      </h3>
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
                        aria-label="Remove Skill"
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  }
                >
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">
                      {skill.description || "Agent skill"}
                    </p>
                  </div>
                </CardAccordionItem>
              ))}
            </Accordion>
          </div>
        )}

        {/* Empty state */}
        {selectedSkills.length === 0 && (
          <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
            <p>No skills assigned. Add skills to enhance this agent&apos;s capabilities.</p>
          </Note>
        )}
      </div>
    </AccordionControl>
  );
};

export default SkillsConfig;
