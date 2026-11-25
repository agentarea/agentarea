// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import {
  isUiNodeInputAttributes,
  type RegistrationFlow,
} from "@ory/client-fetch";
import { Registration } from "@ory/elements-react/theme";
import { AuthLayout } from "@/components/auth/auth-layout";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { getAuthPageConfig } from "@/lib/auth/page-config";
import { getRegistrationFlow, OryPageParams } from "@/lib/ory";
import config from "@/ory.config";

export const metadata: Metadata = {
  title: "Registration",
};

const PROVIDER_TRAITS = new Set([
  "traits.picture",
  "traits.name.first",
  "traits.name.last",
]);

/**
 * Picture and name come from the sign-in provider or are set later in the
 * profile; the signup form asks only for what an account needs.
 */
function withoutProviderTraits(flow: RegistrationFlow): RegistrationFlow {
  return {
    ...flow,
    ui: {
      ...flow.ui,
      nodes: flow.ui.nodes.filter(
        ({ attributes }) =>
          !(
            isUiNodeInputAttributes(attributes) &&
            PROVIDER_TRAITS.has(attributes.name)
          )
      ),
    },
  };
}

export default async function RegistrationPage(props: OryPageParams) {
  const flow = await getRegistrationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = withoutProviderTraits(rewriteFlowForBrowser(flow));
  const registrationConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <Registration flow={browserFlow} config={registrationConfig} />
    </AuthLayout>
  );
}
