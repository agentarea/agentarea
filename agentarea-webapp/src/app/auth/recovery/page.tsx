// Copyright © 2024 Ory Corp

import type { Metadata } from "next";
import { Recovery } from "@ory/elements-react/theme";
import { getRecoveryFlow, OryPageParams } from "@ory/nextjs/app";
import { getTranslations } from "next-intl/server";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("recovery") };
}

export default async function RecoveryPage(props: OryPageParams) {
  const flow = await getRecoveryFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Recovery flow={flow} config={config} />
    </div>
  );
}
