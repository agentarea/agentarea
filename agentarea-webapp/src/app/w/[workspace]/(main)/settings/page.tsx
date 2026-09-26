import type { Metadata } from "next";
import {
  getOryBrowserConfig,
  rewriteFlowForBrowser,
} from "@/lib/auth/browser-config";
import { getSettingsFlow, type OryPageParams } from "@/lib/ory";
import { workspacePath } from "@/lib/workspace-routes";
import config from "@/ory.config";
import SettingsClient from "./SettingsClient";

export const metadata: Metadata = {
  title: "Settings",
};

export default async function SettingsPage(
  props: OryPageParams & { params: Promise<{ workspace: string }> }
) {
  const { workspace } = await props.params;
  // A restarted flow comes back to this workspace, not to Kratos' ui_url.
  const flow = await getSettingsFlow(
    {
      project: {
        ...config.project,
        settings_ui_url: workspacePath(workspace, "/settings"),
      },
    },
    props.searchParams
  );

  if (!flow) return null;

  return (
    <SettingsClient
      flow={rewriteFlowForBrowser(flow)}
      config={await getOryBrowserConfig()}
    />
  );
}
