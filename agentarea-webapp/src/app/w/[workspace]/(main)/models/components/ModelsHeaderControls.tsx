import { getTranslations } from "next-intl/server";
import { Settings } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import { Button } from "@/components/ui/button";

/**
 * The header action of both model tabs. One component, so switching between
 * Connected and Available never resizes, relabels or retargets the button.
 */
export default async function ModelsHeaderControls({
  canAdminister,
}: {
  canAdminister: boolean;
}) {
  const t = await getTranslations("Models");

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
