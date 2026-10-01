import { getTranslations } from "next-intl/server";
import { StatusIndicator } from "@/components/ui/status-indicator";

/** Shown when the members page could not read its data at all. */
export default async function MembersLoadError({
  message,
}: {
  message: string;
}) {
  const t = await getTranslations("MembersPage");

  return (
    <div className="flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
      <div className="min-w-0 space-y-1">
        <StatusIndicator kind="failed" size="sm" className="text-sm font-medium">
          {t("loadFailedTitle")}
        </StatusIndicator>
        <p className="break-words text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}
