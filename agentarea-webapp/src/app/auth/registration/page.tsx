// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Registration } from "@ory/elements-react/theme";
import { getRegistrationFlow, OryPageParams } from "@ory/nextjs/app";
import { getTranslations } from "next-intl/server";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("registration") };
}

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
