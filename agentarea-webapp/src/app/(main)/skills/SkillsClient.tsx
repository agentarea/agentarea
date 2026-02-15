"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Sparkles } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { listSkills, type Skill } from "@/lib/browser-api";
import SkillsTable from "./components/SkillsTable";
import SkillsEmptyState from "./components/SkillsEmptyState";
import CreateSkillDialog from "./components/CreateSkillDialog";

export default function SkillsClient() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const fetchSkills = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, error } = await listSkills();
      if (error) {
        setError("Failed to load skills");
        return;
      }
      setSkills((data as Skill[]) || []);
    } catch (e) {
      setError("Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const handleSkillCreated = () => {
    setCreateDialogOpen(false);
    fetchSkills();
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Skills" }],
        description: "Manage reusable skills that can be assigned to agents",
        controls: (
          <Button
            className="shrink-0 gap-2"
            size="xs"
            onClick={() => setCreateDialogOpen(true)}
            data-test="new-skill-button"
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Skill
          </Button>
        ),
      }}
    >
      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      ) : error ? (
        <div className="flex h-32 items-center justify-center text-red-500">
          {error}
        </div>
      ) : skills.length === 0 ? (
        <SkillsEmptyState onCreateClick={() => setCreateDialogOpen(true)} />
      ) : (
        <SkillsTable skills={skills} />
      )}

      <CreateSkillDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onSuccess={handleSkillCreated}
      />
    </ContentBlock>
  );
}
