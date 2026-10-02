import type { ModelKind } from "@/api/client/types.gen";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** What a non-chat model produces; chat is the default and carries no badge. */
export function ModelKindBadge({
  kind,
  className,
}: {
  kind?: ModelKind | null;
  className?: string;
}) {
  const t = useTranslations("ModelKind");
  if (!kind || kind === "chat") return null;
  return (
    <Badge
      variant="outline"
      className={cn("shrink-0 px-1.5 py-0 text-[10px]", className)}
    >
      {t(kind)}
    </Badge>
  );
}
