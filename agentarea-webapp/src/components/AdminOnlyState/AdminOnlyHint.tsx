"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export type AdminOnlyAction =
  | "budgetCap"
  | "createSecret"
  | "manageSecret"
  | "invitePeople"
  | "manageProvider"
  | "manageMcpAuth"
  | "importPolicies";

/** One muted line next to a control disabled because the viewer is not a workspace admin. */
export default function AdminOnlyHint({
  action,
  className,
}: {
  action: AdminOnlyAction;
  className?: string;
}) {
  const t = useTranslations("AdminOnly");

  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      {t(`hints.${action}`)}
    </p>
  );
}
