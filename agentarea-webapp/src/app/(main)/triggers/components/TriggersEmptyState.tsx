"use client";

import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";

export default function TriggersEmptyState() {
  const t = useTranslations("TriggersPage");

  return (
    <EmptyState
      title={t("noTriggers")}
      description={t("noTriggersDescription")}
      iconsType="triggers"
    />
  );
}
