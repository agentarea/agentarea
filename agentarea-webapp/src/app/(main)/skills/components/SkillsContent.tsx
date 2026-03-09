import { getTranslations } from "next-intl/server";
import { listSkills } from "@/lib/api";
import SkillsList from "./SkillsList";
import type { Skill } from "@/types/skill";

interface SkillsContentProps {
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default async function SkillsContent({
  viewMode,
  searchQuery,
}: SkillsContentProps) {
  const t = await getTranslations("SkillsPage");

  const { data, error } = await listSkills();

  if (error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("error.loadSkills") || "Error loading skills"}
      </div>
    );
  }

  const skills = (data as Skill[]) || [];

  // Filter skills based on search query
  const filteredSkills = searchQuery.trim()
    ? skills.filter(
        (skill) =>
          skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (skill.description && skill.description.toLowerCase().includes(searchQuery.toLowerCase()))
      )
    : skills;

  return (
    <SkillsList
      skills={filteredSkills}
      viewMode={viewMode}
      searchQuery={searchQuery}
    />
  );
}
