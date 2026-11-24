"use client";

import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import AutomationScene from "@/components/illustrations/AutomationScene";

export default function TriggersEmptyState() {
  const t = useTranslations("TriggersPage");

  return (
    <EmptyState
      title={t("noTriggers")}
      visual={<AutomationScene />}
      description={t("noTriggersDescription")}
      hints={[
        { text: t("noTriggersHintCron"), href: "/triggers/create" },
        { text: t("noTriggersHintWebhook"), href: "/triggers/create" },
        { text: t("noTriggersHintHistory") },
      ]}
      action={{ label: t("createTrigger"), href: "/triggers/create" }}
    />
  );
}
