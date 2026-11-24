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

/**
 * The picture trait comes from the sign-in provider; nobody types an image URL
 * into a signup form, so the form does not offer one.
 */
function withoutPicture(flow: RegistrationFlow): RegistrationFlow {
  return {
    ...flow,
    ui: {
      ...flow.ui,
      nodes: flow.ui.nodes.filter(
        ({ attributes }) =>
          !(
            isUiNodeInputAttributes(attributes) &&
            attributes.name === "traits.picture"
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

  const browserFlow = withoutPicture(rewriteFlowForBrowser(flow));
  const registrationConfig = await getAuthPageConfig();

  return (
    <AuthLayout>
      <Registration flow={browserFlow} config={registrationConfig} />
    </AuthLayout>
  );
}
