// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Registration } from "@ory/elements-react/theme";
import { getRegistrationFlow, OryPageParams } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";
import { getOryBrowserConfig, rewriteFlowForBrowser } from "@/lib/auth/browser-config";

export const metadata: Metadata = {
  title: "Registration",
};

export default async function RegistrationPage(props: OryPageParams) {
  const flow = await getRegistrationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Registration flow={rewriteFlowForBrowser(flow)} config={getOryBrowserConfig()} />
    </div>
  );
}
