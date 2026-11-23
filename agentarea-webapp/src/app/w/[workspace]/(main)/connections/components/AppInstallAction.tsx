"use client";

import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Opens, in a new tab, the page where the person picks what the operator's
 * OAuth app may reach: its token reaches nothing they did not pick there.
 * A quiet link beside the other connection actions; a small button only right
 * after a sign-in (`prominent`), when picking is the next step.
 */
export function AppInstallAction({
  url,
  prominent,
}: {
  url: string;
  prominent?: boolean;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");
  const link = (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {t("chooseRepositories")}
      <ExternalLink />
    </a>
  );
  if (prominent) {
    return (
      <div className="flex flex-col items-start gap-1.5">
        <Button asChild size="sm">
          {link}
        </Button>
        <p className="text-xs text-muted-foreground">
          {t("chooseRepositoriesHint")}
        </p>
      </div>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      {t("chooseRepositoriesHint")}
      <Button
        asChild
        variant="link"
        size="xs"
        className="h-auto px-0 [&_svg]:size-3"
      >
        {link}
      </Button>
    </p>
  );
}
