"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import NoticeBanner from "@/components/NoticeBanner";
import { Button } from "@/components/ui/button";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { restoreAgentAction } from "@/lib/server-actions";

export default function ArchivedAgentBanner({ agentId }: { agentId: string }) {
  const t = useTranslations("AgentsPage.archived");
  const router = useWorkspaceRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  const onRestore = () => {
    setFailed(false);
    start(async () => {
      const res = await restoreAgentAction(agentId);
      if (res?.error) {
        setFailed(true);
        return;
      }
      router.refresh();
    });
  };

  return (
    <NoticeBanner
      title={t("title")}
      className="mx-4 mt-3"
      action={
        <Button
          size="xs"
          variant="outline"
          onClick={onRestore}
          isLoading={pending}
        >
          {t("restore")}
        </Button>
      }
    >
      {failed ? t("restoreFailed") : t("description")}
    </NoticeBanner>
  );
}
