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
      <Link href="/models/create">
        <Button className="shrink-0" size="xs" data-test="new-config-button">
          <Settings />
          {t("createButton")}
        </Button>
      </Link>
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
