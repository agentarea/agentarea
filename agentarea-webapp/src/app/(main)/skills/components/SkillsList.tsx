"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import SkillsTable from "./SkillsTable";
import SkillsCard from "./SkillsCard";
import SkillsEmptyState from "./SkillsEmptyState";
import type { Skill } from "@/types/skill";

interface SkillsListProps {
  skills: Skill[];
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default function SkillsList({ 
  skills, 
  viewMode,
  searchQuery 
}: SkillsListProps) {
  const router = useRouter();

  const t = useTranslations("SkillsPage");

  const hasSkills = skills.length > 0;

  // No skills at all (and no search query) -> Global empty state
  if (!hasSkills && !searchQuery) {
    return (
      <SkillsEmptyState onCreateClick={() => router.push("/skills/create")} />
    );
  }

  // No results found for search query
  if (!hasSkills && searchQuery) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center">
        <p className="text-lg font-medium text-muted-foreground">
          {t("noMatchingSkills", { query: searchQuery })}
        </p>
        <Button 
          variant="link" 
          onClick={() => router.push("/skills")}
          className="mt-2"
        >
          {t("clearSearch")}
        </Button>
      </div>
    );
  }

  // Render list/grid
  return (
    <>
      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {skills.map((skill) => (
            <SkillsCard key={skill.id} skill={skill} />
          ))}
        </div>
      ) : (
        <SkillsTable skills={skills} />
      )}
    </>
  );
}
