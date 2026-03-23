// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Registration } from "@ory/elements-react/theme";
import { getRegistrationFlow, OryPageParams } from "@ory/nextjs/app";
import config from "@/ory.config";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";

import { AuthLayout } from "@/components/auth/auth-layout";
import { getAuthPageConfig } from "@/lib/auth/page-config";

export const metadata: Metadata = {
  title: "Registration",
};

export default async function RegistrationPage(props: OryPageParams) {
  const flow = await getRegistrationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const registrationConfig = getAuthPageConfig();

  return (
    <AuthLayout>
      <Registration flow={browserFlow} config={registrationConfig} />
    </AuthLayout>
  );
}
