"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { listSkills, type Skill } from "@/lib/browser-api";
import SkillsTable from "./components/SkillsTable";
import SkillsEmptyState from "./components/SkillsEmptyState";
import CreateSkillDialog from "./components/CreateSkillDialog";

export default function SkillsClient() {
  const t = useTranslations("SkillsPage");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, error } = await listSkills();
      if (error) {
        setError(t("error.loadSkills"));
        return;
      }
      setSkills((data as Skill[]) || []);
    } catch (e) {
      setError(t("error.loadSkills"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const handleSkillCreated = () => {
    setCreateDialogOpen(false);
    fetchSkills();
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: (
          <Button
            className="shrink-0 gap-2"
            size="xs"
            onClick={() => setCreateDialogOpen(true)}
            data-test="new-skill-button"
          >
            <Plus className="mr-2 h-4 w-4" />
            {t("addSkill")}
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
