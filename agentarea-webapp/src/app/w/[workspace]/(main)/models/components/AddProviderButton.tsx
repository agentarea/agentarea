import { getTranslations } from "next-intl/server";
import Link from "@/components/WorkspaceLink";
import { Settings } from "lucide-react";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import { Button } from "@/components/ui/button";
import { getViewerCapabilities } from "@/lib/workspace-context";

/**
 * Header action shared by the Connected and Available tabs, so both pages
 * offer the same way in to adding a provider.
 */
export default async function AddProviderButton() {
  const [t, { canAdminister }] = await Promise.all([
    getTranslations("Models"),
    getViewerCapabilities(),
  ]);

  if (canAdminister) {
    return (
      <Button
        asChild
        className="shrink-0 min-h-11 md:min-h-6"
        size="xs"
        data-test="new-config-button"
      >
        <Link href="/models/create">
          <Settings />
          {t("createButton")}
        </Link>
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <AdminOnlyHint action="manageProvider" />
      <Button
        className="shrink-0"
        size="xs"
        data-test="new-config-button"
        disabled
      >
        <Settings />
        {t("createButton")}
      </Button>
    </div>
  );
}
