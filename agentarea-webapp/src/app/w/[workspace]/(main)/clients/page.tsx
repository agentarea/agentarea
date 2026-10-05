import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import { listClients } from "@/lib/api";
import ClientsData from "./ClientsData";
import ClientsSkeleton from "./ClientsSkeleton";

export const metadata: Metadata = {
  title: "Harnesses",
};

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
  const [t, resolvedSearchParams, cookieStore] = await Promise.all([
    getTranslations("ClientsPage"),
    searchParams,
    cookies(),
  ]);

  // Read tab from URL or fallback to cookie
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieStore.get("tab_clients")?.value;
  const viewMode = tab === "table" ? "table" : "grid";

  return (
    <Suspense fallback={<ClientsSkeleton viewMode={viewMode} />}>
      <ClientsData
        initialResult={initialResult}
        initialView={viewMode}
        loadFailedLabel={t("loadFailed")}
      />
    </Suspense>
  );
}
