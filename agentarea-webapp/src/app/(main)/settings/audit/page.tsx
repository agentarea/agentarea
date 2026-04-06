import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
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
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <AuditLogContent />
      </Suspense>
    </ContentBlock>
  );
}
