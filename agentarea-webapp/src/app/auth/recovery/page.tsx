// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { getRecoveryFlow, OryPageParams } from "@ory/nextjs/app";
import config from "@/ory.config";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { RecoveryForm } from "./recovery-form";

import { AuthLayout } from "@/components/auth/auth-layout";
import { getAuthPageConfig } from "@/lib/auth/page-config";

export const metadata: Metadata = {
  title: "Password Recovery",
};

export default async function RecoveryPage(props: OryPageParams) {
  const flow = await getRecoveryFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const recoveryConfig = getAuthPageConfig();

  return (
    <AuthLayout>
      <RecoveryForm flow={browserFlow} config={recoveryConfig} />
    </AuthLayout>
  );
}
