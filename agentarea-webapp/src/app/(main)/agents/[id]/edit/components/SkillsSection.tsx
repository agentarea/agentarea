"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Check, ChevronsUpDown, Plus, Sparkles, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { listSkills, type Skill } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AgentSkill {
  id: string;
  name: string;
  description?: string | null;
}

interface SkillsSectionProps {
  selectedSkills: AgentSkill[];
  onSkillsChange: (skills: AgentSkill[]) => void;
}

export default function SkillsSection({
  selectedSkills,
  onSkillsChange,
}: SkillsSectionProps) {
  const t = useTranslations("SkillsSection");
  const [open, setOpen] = useState(false);
  const [availableSkills, setAvailableSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchSkills = async () => {
      setLoading(true);
      try {
        const { data } = await listSkills();
        setAvailableSkills((data as Skill[]) || []);
      } finally {
        setLoading(false);
      }
    };
    fetchSkills();
  }, []);

  const handleSelect = (skill: Skill) => {
    const isSelected = selectedSkills.some((s) => s.id === skill.id);
    if (isSelected) {
      onSkillsChange(selectedSkills.filter((s) => s.id !== skill.id));
    } else {
      onSkillsChange([
        ...selectedSkills,
        { id: skill.id, name: skill.name, description: skill.description },
      ]);
    }
    setOpen(false);
  };

  const handleRemove = (skillId: string) => {
    onSkillsChange(selectedSkills.filter((s) => s.id !== skillId));
  };

  const unselectedSkills = availableSkills.filter(
    (skill) => !selectedSkills.some((s) => s.id === skill.id)
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">{t("title")}</h3>
        </div>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-2">
              <Plus className="h-4 w-4" />
              {t("addSkill")}
              <ChevronsUpDown className="ml-1 h-4 w-4 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[300px] p-0" align="end">
            <Command>
              <CommandInput placeholder={t("searchPlaceholder")} />
              <CommandList>
                <CommandEmpty>
                  {loading ? (
                    t("loading")
                  ) : availableSkills.length === 0 ? (
                    <div className="p-4 text-center">
                      <p className="text-sm text-muted-foreground">
                        {t("noSkillsAvailable")}
                      </p>
                      <Link href="/skills">
                        <Button variant="link" size="sm" className="mt-2">
                          {t("createSkill")}
                        </Button>
                      </Link>
                    </div>
                  ) : (
                    t("noSkillsFound")
                  )}
                </CommandEmpty>
                <CommandGroup>
                  {unselectedSkills.map((skill) => (
                    <CommandItem
                      key={skill.id}
                      value={skill.name}
                      onSelect={() => handleSelect(skill)}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          selectedSkills.some((s) => s.id === skill.id)
                            ? "opacity-100"
                            : "opacity-0"
                        )}
                      />
                      <div className="flex flex-col">
                        <span>{skill.name}</span>
                        {skill.description && (
                          <span className="text-xs text-muted-foreground">
                            {skill.description}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>

      {selectedSkills.length === 0 ? (
        <div className="rounded-md border border-dashed p-4 text-center">
          <p className="text-sm text-muted-foreground">
            {t("noSkillsAssigned")}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {selectedSkills.map((skill) => (
            <Badge
              key={skill.id}
              variant="secondary"
              className="gap-1 py-1.5 pl-3 pr-1"
            >
              <Link
                href={`/skills/${skill.id}`}
                className="hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {skill.name}
              </Link>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 hover:bg-transparent"
                onClick={() => handleRemove(skill.id)}
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
