// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { AuthLayout } from "@/components/auth/auth-layout";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { getAuthPageConfig } from "@/lib/auth/page-config";
import { getRecoveryFlow, OryPageParams } from "@/lib/ory";
import config from "@/ory.config";
import { RecoveryForm } from "./recovery-form";

export const metadata: Metadata = {
  title: "Password Recovery",
};

export default async function RecoveryPage(props: OryPageParams) {
  const flow = await getRecoveryFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const recoveryConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <RecoveryForm flow={browserFlow} config={recoveryConfig} />
    </AuthLayout>
  );
}
