import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ProvidersData from "../components/ProvidersData";
import ProvidersSkeleton from "../components/ProvidersSkeleton";
import { MODELS_VIEW_COOKIE, resolveViewMode } from "../components/viewMode";

interface ProviderConfigsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

// Connected tab. Header, search and view toggle come from the shared layout.
export default async function ProviderConfigsPage({
  searchParams,
}: ProviderConfigsPageProps) {
  const [t, resolvedSearchParams, cookieStore] = await Promise.all([
    getTranslations("Models"),
    searchParams,
    cookies(),
  ]);
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";
  const tab = resolveViewMode(
    resolvedSearchParams.tab,
    cookieStore.get(MODELS_VIEW_COOKIE)?.value
  );

  const configColumns = [
    { header: t("table.name"), barClassName: "h-4 w-32" },
    { header: t("table.provider"), barClassName: "h-4 w-24" },
    { header: t("table.models"), barClassName: "h-5 w-28 rounded-full" },
  ];

  return (
    <Suspense
      key={searchQuery}
      fallback={
        <ProvidersSkeleton
          viewMode={tab}
          columns={configColumns}
        />
      }
    >
      <ProvidersData searchQuery={searchQuery} viewMode={tab} />
    </Suspense>
  );
}
