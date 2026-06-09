import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Settings } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import ProvidersData from "./components/ProvidersData";

export const metadata: Metadata = {
  title: "Models",
};

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

interface ProviderConfigsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProviderConfigsPage({
  searchParams,
}: ProviderConfigsPageProps) {
  const t = await getTranslations("Models");
  const resolvedSearchParams = await searchParams;

  // View mode: prefer URL, fall back to cookie, default to grid.
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_admin_provider-configs")?.value;
  const urlView = asString(resolvedSearchParams.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "list"
        ? "list"
        : "grid";

  const hostingParam = asString(resolvedSearchParams.hosting);
  const tab: "all" | "cloud" | "local" =
    hostingParam === "cloud" || hostingParam === "local" ? hostingParam : "all";

  const groupParam = asString(resolvedSearchParams.group);
  const group: "none" | "status" | "hosting" =
    groupParam === "status" || groupParam === "hosting" ? groupParam : "none";

  const orderParam = asString(resolvedSearchParams.order);
  const order: "name" | "status" =
    orderParam === "status" ? "status" : "name";

  const search = asString(resolvedSearchParams.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/admin/provider-configs" }],
        description: t("description"),
        controls: (
          <Link href="/admin/provider-configs/create">
            <Button
              className="shrink-0 gap-2"
              size="xs"
              data-test="new-config-button"
            >
              <Settings className="mr-2 h-4 w-4" />
              {t("createButton")}
            </Button>
          </Link>
        ),
      }}
      className="overflow-hidden p-0"
    >
      <Suspense
        key={`${view}-${tab}-${group}-${order}-${search}`}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <ProvidersData initial={{ view, tab, group, order, search }} />
      </Suspense>
    </ContentBlock>
  );
}
