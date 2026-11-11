import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { listClients } from "@/lib/api";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import ClientsData from "./ClientsData";
import ClientsSkeleton from "./ClientsSkeleton";

export const metadata: Metadata = {
  title: "Harnesses",
};

interface ClientsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ClientsPage({ searchParams }: ClientsPageProps) {
  const initialResult = listClients().then(
    (apiResult) => ({ apiResult }),
    (exception: unknown) => ({ exception })
  );
  const [t, resolvedSearchParams, uiPrefs] = await Promise.all([
    getTranslations("ClientsPage"),
    searchParams,
    readUiPrefs(),
  ]);

  // Read tab from URL, else the remembered view
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : uiPrefs.views["tab_clients"];
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
