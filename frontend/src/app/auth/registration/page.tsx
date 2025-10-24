// Copyright © 2024 Ory Corp

import { Registration } from "@ory/elements-react/theme";
import { getRegistrationFlow, OryPageParams } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export default async function RegistrationPage(props: OryPageParams) {
  const flow = await getRegistrationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Registration flow={flow} config={config} />
    </div>
  );
}
