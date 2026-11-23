"use client";

import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * Opens, in a new tab, the page where the person picks what the operator's
 * OAuth app may reach: its token reaches nothing they did not pick there.
 * `prominent` right after a sign-in, when this is the next step.
 */
export function AppInstallAction({
  url,
  prominent,
  size,
  className,
}: {
  url: string;
  prominent?: boolean;
  size?: ButtonProps["size"];
  className?: string;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");
  return (
    <div className="flex flex-col gap-1.5">
      <Button
        asChild
        size={size}
        variant={prominent ? "default" : "outline"}
        className={className}
      >
        <a href={url} target="_blank" rel="noopener noreferrer">
          {t("chooseRepositories")}
          <ExternalLink />
        </a>
      </Button>
      <p className="text-xs text-muted-foreground">
        {t("chooseRepositoriesHint")}
      </p>
    </div>
  );
}
