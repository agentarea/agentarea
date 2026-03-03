"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import SkillsTable from "./SkillsTable";
import SkillsCard from "./SkillsCard";
import SkillsEmptyState from "./SkillsEmptyState";
import CreateSkillDialog from "./CreateSkillDialog";
import { useState } from "react";
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
  const t = useTranslations("SkillsPage");
  const router = useRouter();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const handleSkillCreated = () => {
    setCreateDialogOpen(false);
    router.refresh();
  };

  const hasSkills = skills.length > 0;

  // No skills at all (and no search query) -> Global empty state
  if (!hasSkills && !searchQuery) {
    return (
      <>
        <SkillsEmptyState onCreateClick={() => setCreateDialogOpen(true)} />
        <CreateSkillDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          onSuccess={handleSkillCreated}
        />
      </>
    );
  }

  // No results found for search query
  if (!hasSkills && searchQuery) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center">
        <p className="text-lg font-medium text-muted-foreground">
          No skills match your search &quot;{searchQuery}&quot;
        </p>
        <Button 
          variant="link" 
          onClick={() => router.push("/skills")}
          className="mt-2"
        >
          Clear search
        </Button>
      </div>
    );
  }

  // Render list/grid
  return (
    <>
      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {skills.map((skill) => (
            <SkillsCard key={skill.id} skill={skill} />
          ))}
        </div>
      ) : (
        <SkillsTable skills={skills} />
      )}
      
      {/* Hidden dialog for potential future use or consistency if needed, 
          but currently only used in empty state above. 
          Actually, we don't need it here unless there's another trigger. */}
    </>
  );
}
