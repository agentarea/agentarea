"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import CreateSkillDialog from "./CreateSkillDialog";

export default function CreateSkillButton() {
  const t = useTranslations("SkillsPage");
  const router = useRouter();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const handleSkillCreated = () => {
    setCreateDialogOpen(false);
    router.refresh();
  };

  return (
    <>
      <Button
        className="shrink-0 gap-2"
        size="xs"
        onClick={() => setCreateDialogOpen(true)}
        data-test="new-skill-button"
      >
        <Plus className="mr-2 h-4 w-4" />
        {t("addSkill")}
      </Button>

      <CreateSkillDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onSuccess={handleSkillCreated}
      />
    </>
  );
}
