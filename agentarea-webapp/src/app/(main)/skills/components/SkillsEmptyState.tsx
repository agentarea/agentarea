"use client";

import { Sparkles, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface SkillsEmptyStateProps {
  onCreateClick: () => void;
}

export default function SkillsEmptyState({ onCreateClick }: SkillsEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Sparkles className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="mb-2 text-lg font-semibold">No skills yet</h3>
      <p className="mb-6 max-w-sm text-muted-foreground">
        Skills are reusable capabilities that can be assigned to agents.
        Create your first skill to get started.
      </p>
      <Button onClick={onCreateClick} className="gap-2">
        <Plus className="h-4 w-4" />
        Add Skill
      </Button>
    </div>
  );
}
