import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { listClients } from "@/lib/api";
import ClientsData from "./ClientsData";
import ClientsSkeleton from "./ClientsSkeleton";

interface ClientsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ClientsPage({
  searchParams,
}: ClientsPageProps) {
  const initialResult = listClients().then(
    (apiResult) => ({ apiResult }),
    (exception: unknown) => ({ exception })
  );
  const [t, resolvedSearchParams] = await Promise.all([
    getTranslations("ClientsPage"),
    searchParams,
  ]);

  return (
    <Suspense
      fallback={
        <ClientsSkeleton
          title={t("title")}
          description={t("description")}
          viewMode={
            typeof resolvedSearchParams.tab === "string"
              ? resolvedSearchParams.tab
              : "grid"
          }
        />
      }
    >
      <ClientsData
        initialResult={initialResult}
        loadFailedLabel={t("loadFailed")}
      />
    </Suspense>
  );
}
