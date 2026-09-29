import { getTranslations } from "next-intl/server";
import { AlertTriangle } from "lucide-react";

/** Shown when the members page could not read its data at all. */
export default async function MembersLoadError({
  message,
}: {
  message: string;
}) {
  const t = await getTranslations("MembersPage");

  return (
    <div className="flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-medium">{t("loadFailedTitle")}</p>
        <p className="break-words text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}
