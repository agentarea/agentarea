"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function CreateSkillButton() {
  const t = useTranslations("SkillsPage");

  return (
    <Button
      className="shrink-0"
      size="xs"
      asChild
      data-test="new-skill-button"
    >
      <Link href="/skills/create">
        <Plus />
        {t("addSkill")}
      </Link>
    </Button>
  );
}
