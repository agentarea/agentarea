"use client";

import { useTranslations } from "next-intl";
import type { SettingsFlow } from "@ory/client-fetch";
import type { OryClientConfiguration } from "@ory/elements-react";
import type { Workspace } from "@/lib/workspaces";
import ExportWorkspaceButton from "./components/ExportWorkspaceButton";
import LanguageSelect from "./components/LanguageSelect";
import ProfileForm from "./components/ProfileForm";
import SettingsRow from "./components/SettingsRow";
import { SettingsSection } from "./components/SettingsSection";
import ThemeSelect from "./components/ThemeSelect";
import WorkspaceLogoRow from "./components/WorkspaceLogoRow";

/** The settings page's sections, under the header page.tsx draws. */
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

  return (
    <>
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
    </>
  );
}
