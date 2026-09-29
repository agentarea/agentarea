import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { TableSkeleton } from "@/components/Skeleton";
import APIKeysContent from "./APIKeysContent";
import CreateAPIKeyButton from "./components/CreateAPIKeyButton";

export const metadata: Metadata = {
  title: "API Keys",
};

export default async function APIKeysPage() {
  const t = await getTranslations("APIKeysPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Settings", href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
        controls: <CreateAPIKeyButton />,
      }}
    >
      <Suspense
        fallback={
          <TableSkeleton
            rows={6}
            columns={[
              { header: t("table.name"), barClassName: "h-4 w-32" },
              {
                header: t("table.tokenPrefix"),
                headerClassName: "w-[140px]",
                barClassName: "h-4 w-20",
              },
              {
                header: t("table.status"),
                headerClassName: "w-[120px]",
                barClassName: "h-5 w-16 rounded-full",
              },
              {
                header: t("table.created"),
                headerClassName: "w-[120px]",
                barClassName: "h-4 w-20",
              },
              {
                header: t("table.expires"),
                headerClassName: "w-[120px]",
                barClassName: "h-4 w-20",
              },
              {
                header: t("table.lastUsed"),
                headerClassName: "w-[150px]",
                barClassName: "h-4 w-20",
              },
              { header: "", headerClassName: "w-0", barClassName: "hidden" },
            ]}
          />
        }
      >
        <APIKeysContent />
      </Suspense>
    </ContentBlock>
  );
}
