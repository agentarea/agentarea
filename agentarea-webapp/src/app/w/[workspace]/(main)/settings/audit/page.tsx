import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { TableSkeleton } from "@/components/Skeleton";
import AuditLogContent from "./AuditLogContent";

export const metadata: Metadata = {
  title: "Audit Log",
};

export default async function AuditLogPage() {
  const t = await getTranslations("AuditLogPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Settings", href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
      }}
    >
      <Suspense
        fallback={
          <TableSkeleton
            rows={10}
            columns={[
              { header: "", barClassName: "h-4 w-4" },
              { header: t("table.action"), barClassName: "h-4 w-28" },
              { header: t("table.resource"), barClassName: "h-4 w-32" },
              { header: t("table.actor"), barClassName: "h-4 w-24" },
              { header: t("table.ip"), barClassName: "h-4 w-20" },
              { header: t("table.when"), barClassName: "h-4 w-24" },
            ]}
          />
        }
      >
        <AuditLogContent />
      </Suspense>
    </ContentBlock>
  );
}
