// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Verification } from "@ory/elements-react/theme";
import { AuthLayout } from "@/components/auth/auth-layout";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { getAuthPageConfig } from "@/lib/auth/page-config";
import { getVerificationFlow, OryPageParams } from "@/lib/ory";
import config from "@/ory.config";

export const metadata: Metadata = {
  title: "Verification",
};

export default async function VerificationPage(props: OryPageParams) {
  const flow = await getVerificationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const verificationConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <Verification
        flow={browserFlow}
        config={verificationConfig}
      />
    </AuthLayout>
  );
}
