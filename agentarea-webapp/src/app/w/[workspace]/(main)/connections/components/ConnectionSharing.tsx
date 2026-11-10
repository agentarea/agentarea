"use client";

import { useOptimistic, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Lock, Users } from "lucide-react";
import FormError from "@/components/FormError";
import {
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiErrorMessage, type ApiResultLike } from "@/lib/api-errors";

/** Marks a connection only its creator, and agents it was lent to, may use. */
export function PersonalBadge() {
  const t = useTranslations("MCPServersPage.sharing");
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          size="sm"
          variant="secondary"
          className="h-5 shrink-0 gap-1 px-1.5 font-normal"
        >
          <Lock className="h-3 w-3" aria-hidden />
          {t("personal")}
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="top">{t("personalHint")}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Who may call through a connection. Its creator shares it with the workspace
 * or takes it back with the switch in the card head; anyone else only reads it.
 */
export function ConnectionSharingSection({
  personal,
  isOwner,
  onShare,
}: {
  personal: boolean;
  isOwner: boolean;
  onShare: (shared: boolean) => Promise<ApiResultLike>;
}) {
  const t = useTranslations("MCPServersPage.sharing");
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();
  const [shared, setShared] = useOptimistic(!personal);

  const change = (next: boolean) =>
    startSaving(async () => {
      setShared(next);
      const result = await onShare(next);
      setError(result?.error ? apiErrorMessage(result, t("saveFailed")) : null);
    });

  return (
    <SectionCard>
      <SectionCardHead
        icon={shared ? <Users /> : <Lock />}
        title={t("title")}
        action={
          isOwner ? (
            <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
              {t("share")}
              <Switch
                size="xs"
                checked={shared}
                onCheckedChange={change}
                disabled={saving}
              />
            </label>
          ) : undefined
        }
      />
      <div className="space-y-2 px-[15px] py-3">
        <p className="text-[12.5px]">
          {shared
            ? t("shared")
            : isOwner
              ? t("personalOwn")
              : t("personalOther")}
        </p>
        {!shared && !isOwner && <p className="note">{t("ownerOnly")}</p>}
        {error && <FormError>{error}</FormError>}
      </div>
    </SectionCard>
  );
}
