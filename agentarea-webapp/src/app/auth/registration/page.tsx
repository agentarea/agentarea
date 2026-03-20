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

  const browserFlow = rewriteFlowForBrowser(flow);
  const browserConfig = getOryBrowserConfig();
  const registrationConfig = {
    ...browserConfig,
    project: {
      ...browserConfig.project,
      logo_light_url: "/logo.svg",
    },
  };

  return (
    <div className="relative flex min-h-screen w-full flex-col sm:items-center sm:justify-center sm:px-4 sm:py-10">
      <div className="pointer-events-none fixed inset-0 bg-background" />
      <div className="pointer-events-none fixed inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:hidden" />
      <div className="pointer-events-none fixed inset-0 hidden bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-25 dark:block" />

      <div className="login-ory relative z-10 w-full max-w-md my-auto flex flex-col sm:h-auto">
        <Registration flow={browserFlow} config={registrationConfig} />
      </div>
    </div>
  );
}
