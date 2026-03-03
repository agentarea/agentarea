"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function CreateSkillButton() {
  const t = useTranslations("SkillsPage");

  return (
    <Button
      className="shrink-0 gap-2"
      size="xs"
      asChild
      data-test="new-skill-button"
    >
      <Link href="/skills/create">
        <Plus className="mr-2 h-4 w-4" />
        {t("addSkill")}
      </Link>
    </Button>
  );
}
