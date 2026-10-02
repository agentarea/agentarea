import type { Metadata } from "next";
import { cookies } from "next/headers";
import ClientsView from "./ClientsView";

export const metadata: Metadata = {
  title: "Harnesses",
};

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const resolvedSearchParams = await searchParams;

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieStore.get("tab_clients")?.value;

  return <ClientsView initialView={tab === "table" ? "table" : "grid"} />;
}
