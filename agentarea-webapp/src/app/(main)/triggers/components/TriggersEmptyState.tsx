"use client";

import { useTranslations } from "next-intl";
import { Zap, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface TriggersEmptyStateProps {
  onCreateClick: () => void;
}

export default function TriggersEmptyState({ onCreateClick }: TriggersEmptyStateProps) {
  const t = useTranslations("TriggersPage");

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Zap className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="mb-2 text-lg font-semibold">{t("noTriggers")}</h3>
      <p className="mb-6 max-w-sm text-muted-foreground">
        {t("noTriggersDescription")}
      </p>
      <Button onClick={onCreateClick} className="gap-2">
        <Plus className="h-4 w-4" />
        {t("createTrigger")}
      </Button>
    </div>
  );
}
