import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import BillingContent from "./BillingContent";
import BillingSkeleton from "./BillingSkeleton";

export const metadata: Metadata = {
  title: "Billing",
};

export default async function BillingPage() {
  const t = await getTranslations("BillingPage");
  const tSettings = await getTranslations("SettingsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tSettings("title"), href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
      }}
    >
      <Suspense fallback={<BillingSkeleton />}>
        <BillingContent />
      </Suspense>
    </ContentBlock>
  );
}
