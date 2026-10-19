"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import BaseModal from "@/components/BaseModal";
import { Button } from "@/components/ui/button";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { useCatalogFetchError } from "@/hooks/useCatalogFetchError";
import { apiErrorDetail, catalogFetchFailure } from "@/lib/api-errors";
import { updateInstalledSkillAction } from "@/lib/server-actions";

/**
 * A workspace admin moves an installed catalog skill to the registry's current
 * version. A skill edited here is refused (skill_customized); only then may
 * the admin discard the edit and update anyway.
 */
export default function UpdateSkillButton({
  skill,
  onUpdated,
  onError,
}: {
  skill: {
    id: string;
    name: string;
    update_available?: boolean | null;
  };
  onUpdated: () => void;
  onError: (message: string | null) => void;
}) {
  const t = useTranslations("SkillsPage.update");
  const { canAdminister } = useViewerCapabilities();
  const catalogFetchError = useCatalogFetchError();
  const [pending, startTransition] = useTransition();
  // The 409 that offers to discard the edit, with the server's reason.
  const [customizedRefusal, setCustomizedRefusal] = useState<string | null>(
    null
  );

  if (!canAdminister || !skill.update_available) return null;

  const update = (discardChanges: boolean) =>
    updateInstalledSkillAction(skill.id, { discardChanges });

  const onClick = () => {
    onError(null);
    startTransition(async () => {
      const result = await update(false);
      if (!result.error) {
        onUpdated();
        return;
      }
      if (catalogFetchFailure(result) === "customized") {
        setCustomizedRefusal(apiErrorDetail(result, t("failed")));
        return;
      }
      onError(catalogFetchError(result, t("failed")));
    });
  };

  const discardAndUpdate = async () => {
    const result = await update(true);
    if (result.error) {
      setCustomizedRefusal(catalogFetchError(result, t("failed")));
      return false;
    }
    setCustomizedRefusal(null);
    onUpdated();
  };

  return (
    <>
      <Button size="xs" variant="outline" onClick={onClick} isLoading={pending}>
        {!pending && <RefreshCw />}
        {t("update")}
      </Button>
      <BaseModal
        type="delete"
        open={customizedRefusal !== null}
        onOpenChange={(open) => {
          if (!open) setCustomizedRefusal(null);
        }}
        title={t("discardTitle")}
        description={t("discardDescription", { name: skill.name })}
        error={customizedRefusal}
        confirmLabel={t("discardAndUpdate")}
        onConfirm={discardAndUpdate}
      />
    </>
  );
}
