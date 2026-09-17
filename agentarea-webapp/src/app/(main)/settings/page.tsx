import type { Metadata } from "next";
import {
  getOryBrowserConfig,
  rewriteFlowForBrowser,
} from "@/lib/auth/browser-config";
import { getSettingsFlow, type OryPageParams } from "@/lib/ory";
import config from "@/ory.config";
import SettingsClient from "./SettingsClient";

export const metadata: Metadata = {
  title: "Settings",
};

export default async function SettingsPage(props: OryPageParams) {
  const flow = await getSettingsFlow(config, props.searchParams);

  if (!flow) return null;

  return (
    <SettingsClient
      flow={rewriteFlowForBrowser(flow)}
      config={await getOryBrowserConfig()}
    />
  );
}
