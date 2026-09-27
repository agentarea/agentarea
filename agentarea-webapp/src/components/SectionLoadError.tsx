"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";

/** A part of the page failed to load: say so, with a Retry that re-runs the server render. */
export default function SectionLoadError({ message }: { message: string }) {
  const router = useWorkspaceRouter();
  const t = useTranslations("Common");

  return (
    <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start">
      <FormError className="flex-1">{message}</FormError>
      <Button
        size="xs"
        variant="outline"
        className="self-start"
        onClick={() => router.refresh()}
      >
        <RefreshCw />
        {t("retry")}
      </Button>
    </div>
  );
}
