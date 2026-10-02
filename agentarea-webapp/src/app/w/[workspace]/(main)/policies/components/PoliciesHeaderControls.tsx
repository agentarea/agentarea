"use client";

import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function PoliciesHeaderControls() {
  const t = useTranslations("PoliciesPage");

  return (
    <Button size="xs" className="shrink-0" asChild>
      <Link href="/policies/new">
        <Plus />
        {t("newPolicy")}
      </Link>
    </Button>
  );
}
