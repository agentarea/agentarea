"use client";

import { useTranslations } from "next-intl";
import { LogOut } from "lucide-react";
import { ToolbarButton } from "@/components/ui/toolbar";
import { useAuth } from "@/hooks/useAuth";

export default function LogoutButton() {
  const t = useTranslations("SettingsPage");
  const { signOut } = useAuth();

  return (
    <ToolbarButton onClick={signOut}>
      <LogOut className="h-3.5 w-3.5 text-muted-foreground" />
      {t("logout")}
    </ToolbarButton>
  );
}
