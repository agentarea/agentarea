import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import {
  getOryBrowserConfig,
  rewriteFlowForBrowser,
} from "@/lib/auth/browser-config";
import { getSettingsFlow, type OryPageParams } from "@/lib/ory";
import {
  getViewerCapabilities,
  getWorkspaceContext,
} from "@/lib/workspace-context";
import { workspacePath } from "@/lib/workspace-routes";
import config from "@/ory.config";
import LogoutButton from "./components/LogoutButton";
import MessengersSection from "./components/MessengersSection";
import SettingsSkeleton from "./components/SettingsSkeleton";
import SettingsClient from "./SettingsClient";

export const metadata: Metadata = {
  title: "Settings",
};

type SettingsPageProps = OryPageParams & {
  params: Promise<{ workspace: string }>;
};

export default async function SettingsPage(props: SettingsPageProps) {
  const t = await getTranslations("SettingsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }, { label: t("profile.title") }],
        controls: <LogoutButton />,
      }}
    >
      <div className="mx-auto max-w-[680px] space-y-8 pb-12 pt-3">
        <Suspense fallback={<SettingsSkeleton />}>
          <SettingsContent {...props} />
        </Suspense>
      </div>
    </ContentBlock>
  );
}

async function SettingsContent(props: SettingsPageProps) {
  const { workspace } = await props.params;
  // A restarted flow comes back to this workspace, not to Kratos' ui_url.
  const [flow, { canAdminister }, { active }] = await Promise.all([
    getSettingsFlow(
      {
        project: {
          ...config.project,
          settings_ui_url: workspacePath(workspace, "/settings"),
        },
      },
      props.searchParams
    ),
    getViewerCapabilities(),
    getWorkspaceContext(),
  ]);

  if (!flow) return null;
  if (!active) {
    throw new Error("Settings rendered outside a workspace of the caller");
  }

  const linkBot = (await props.searchParams).link_telegram;

  return (
    <>
      <SettingsClient
        flow={rewriteFlowForBrowser(flow)}
        config={await getOryBrowserConfig()}
        canAdminister={canAdminister}
        workspace={active}
      />
      <MessengersSection
        linkBot={typeof linkBot === "string" ? linkBot : undefined}
      />
    </>
  );
}
