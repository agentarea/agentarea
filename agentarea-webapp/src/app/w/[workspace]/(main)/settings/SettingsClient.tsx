"use client";

import { useTranslations } from "next-intl";
import type { SettingsFlow } from "@ory/client-fetch";
import type { OryClientConfiguration } from "@ory/elements-react";
import { FileDown, Globe, LogOut, Moon } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useAuth } from "@/hooks/useAuth";
import ExportWorkspaceButton from "./components/ExportWorkspaceButton";
import LanguageSelect from "./components/LanguageSelect";
import ProfileForm from "./components/ProfileForm";
import SettingsRow from "./components/SettingsRow";

export default function SettingsClient({
  flow,
  config,
  canAdminister,
}: {
  flow: SettingsFlow;
  config: OryClientConfiguration;
  canAdminister: boolean;
}) {
  const t = useTranslations("SettingsPage");
  const { signOut } = useAuth();

  const handleLogout = async () => {
    await signOut();
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }, { label: t("profile.title") }],
        description: t("description"),
        controls: (
          <Button
            onClick={handleLogout}
            variant="outline"
            size="sm"
            className="gap-1"
          >
            <LogOut />
            {t("logout")}
          </Button>
        ),
      }}
    >
      {/* Compact Main Content */}
      <div className="mx-auto max-w-4xl">
        <div className="space-y-4">
          {/* Compact Profile Section */}
          <section id="profile" className="border-0 p-0">
            <ProfileForm key={flow.id} flow={flow} config={config} />
          </section>

          {/* Compact Preferences Section */}
          <section id="preferences" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                {t("preferences.title")}
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {t("preferences.description")}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4">
              <SettingsRow
                icon={Globe}
                title={t("preferences.language")}
                description={t("preferences.languageDescription")}
              >
                <LanguageSelect />
              </SettingsRow>
              <SettingsRow
                icon={Moon}
                title={t("preferences.theme")}
                description={t("preferences.themeDescription")}
              >
                <ThemeToggle />
              </SettingsRow>
            </div>
          </section>

          {canAdminister && (
            <section id="workspace" className="border-0 p-0">
              <div className="px-4 pt-3">
                <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                  {t("workspace.title")}
                </h2>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                  {t("workspace.description")}
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3 p-4">
                <SettingsRow
                  icon={FileDown}
                  title={t("workspace.exportTitle")}
                  description={t("workspace.exportDescription")}
                >
                  <ExportWorkspaceButton />
                </SettingsRow>
              </div>
            </section>
          )}
        </div>
      </div>
    </ContentBlock>
  );
}
