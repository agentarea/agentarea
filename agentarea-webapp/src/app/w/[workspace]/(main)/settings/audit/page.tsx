import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { TableSkeleton } from "@/components/Skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { listAuditActorOptions } from "./actions";
import AuditExportButton from "./AuditExportButton";
import { auditFiltersKey, parseAuditFilters } from "./auditFilters";
import AuditLogContent from "./AuditLogContent";
import AuditLogToolbar, { ActorFilter } from "./AuditLogToolbar";

export const metadata: Metadata = {
  title: "Audit Log",
};

async function ActorFilterData() {
  return <ActorFilter options={await listAuditActorOptions()} />;
}

export default async function AuditLogPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const t = await getTranslations("AuditLogPage");
  const [filters, { canAdminister }] = await Promise.all([
    searchParams.then(parseAuditFilters),
    getViewerCapabilities(),
  ]);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Settings", href: "/settings" },
          { label: t("title") },
        ],
        controls: canAdminister ? <AuditExportButton /> : undefined,
      }}
      subheader={
        canAdminister ? (
          <SubheaderToolbar
            controls={
              <AuditLogToolbar
                actorFilter={
                  <Suspense fallback={<ActorFilter options={[]} />}>
                    <ActorFilterData />
                  </Suspense>
                }
              />
            }
          />
        ) : undefined
      }
    >
      <Suspense
        key={auditFiltersKey(filters)}
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
        <AuditLogContent filters={filters} />
      </Suspense>
    </ContentBlock>
  );
}
