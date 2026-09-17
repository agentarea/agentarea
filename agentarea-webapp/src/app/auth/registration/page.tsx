// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Registration } from "@ory/elements-react/theme";
import { AuthLayout } from "@/components/auth/auth-layout";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { getAuthPageConfig } from "@/lib/auth/page-config";
import { getRegistrationFlow, OryPageParams } from "@/lib/ory";
import config from "@/ory.config";

export const metadata: Metadata = {
  title: "Registration",
};

export default async function RegistrationPage(props: OryPageParams) {
  const flow = await getRegistrationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const registrationConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <Registration
        flow={browserFlow}
        config={registrationConfig}
      />
    </AuthLayout>
  );
}
