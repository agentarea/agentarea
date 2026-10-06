"use client";

import { useTranslations } from "next-intl";
import type { SettingsFlow } from "@ory/client-fetch";
import type { OryClientConfiguration } from "@ory/elements-react";
import { LogOut } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { ToolbarButton } from "@/components/ui/toolbar";
import { useAuth } from "@/hooks/useAuth";
import type { Workspace } from "@/lib/workspaces";
import ExportWorkspaceButton from "./components/ExportWorkspaceButton";
import LanguageSelect from "./components/LanguageSelect";
import ProfileForm from "./components/ProfileForm";
import SettingsRow from "./components/SettingsRow";
import { SettingsSection } from "./components/SettingsSection";
import ThemeSelect from "./components/ThemeSelect";
import WorkspaceLogoRow from "./components/WorkspaceLogoRow";

export default function SettingsClient({
  flow,
  config,
  canAdminister,
  workspace,
}: {
  flow: SettingsFlow;
  config: OryClientConfiguration;
  canAdminister: boolean;
  workspace: Workspace;
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
        controls: (
          <ToolbarButton onClick={handleLogout}>
            <LogOut className="h-3.5 w-3.5 text-muted-foreground" />
            {t("logout")}
          </ToolbarButton>
        ),
      }}
    >
      <div className="mx-auto max-w-[680px] space-y-8 pb-12 pt-3">
        <ProfileForm key={flow.id} flow={flow} config={config} />

        <SettingsSection title={t("preferences.title")}>
          <SettingsRow
            title={t("preferences.language")}
            description={t("preferences.languageDescription")}
          >
            <LanguageSelect />
          </SettingsRow>
          <SettingsRow
            title={t("preferences.theme")}
            description={t("preferences.themeDescription")}
          >
            <ThemeSelect />
          </SettingsRow>
        </SettingsSection>

        {canAdminister && (
          <SettingsSection
            title={t("workspace.title")}
            description={t("workspace.description", { name: workspace.name })}
          >
            <WorkspaceLogoRow workspace={workspace} />
            <SettingsRow
              title={t("workspace.exportTitle")}
              description={t("workspace.exportDescription")}
            >
              <ExportWorkspaceButton />
            </SettingsRow>
          </SettingsSection>
        )}
      </div>
    </ContentBlock>
  );
}
