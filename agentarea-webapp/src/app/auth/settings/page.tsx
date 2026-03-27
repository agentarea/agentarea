// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { SessionProvider } from "@ory/elements-react/client";
import { Settings } from "@ory/elements-react/theme";
import { getSettingsFlow, OryPageParams } from "@ory/nextjs/app";
import config from "@/ory.config";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";

import { AuthLayout } from "@/components/auth/auth-layout";
import { getAuthPageConfig } from "@/lib/auth/page-config";

export const metadata: Metadata = {
  title: "Account Settings",
};

export default async function SettingsPage(props: OryPageParams) {
  const flow = await getSettingsFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const settingsConfig = getAuthPageConfig();

  return (
    <AuthLayout>
      <SessionProvider>
        <Settings flow={browserFlow} config={settingsConfig} />
      </SessionProvider>
    </AuthLayout>
  );
}
