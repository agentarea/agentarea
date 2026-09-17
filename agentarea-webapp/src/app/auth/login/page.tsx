import type { Metadata } from "next";
import { Login } from "@ory/elements-react/theme";
import { AuthLayout } from "@/components/auth/auth-layout";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { getAuthPageConfig } from "@/lib/auth/page-config";
import { getLoginFlow, type OryPageParams } from "@/lib/ory";
import config from "@/ory.config";

export const metadata: Metadata = {
  title: "Login",
};

export default async function LoginPage(props: OryPageParams) {
  const flow = await getLoginFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const loginConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <Login
        flow={browserFlow}
        config={loginConfig}
       
      />
    </AuthLayout>
  );
}
