import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import TriggersContent from "./components/TriggersContent";
import CreateTriggerButton from "./components/CreateTriggerButton";

export const metadata = {
  title: "Automation",
};

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

export default async function TriggersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("TriggersPage");
  const resolvedSearchParams = await searchParams;

  // View mode: prefer URL, fall back to cookie, default to list.
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_triggers")?.value;
  const urlView = asString(resolvedSearchParams.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const typeParam = asString(resolvedSearchParams.type);
  const tab: "all" | "cron" | "webhook" =
    typeParam === "cron" || typeParam === "webhook" ? typeParam : "all";

  const groupParam = asString(resolvedSearchParams.group);
  const group: "none" | "status" | "type" | "agent" =
    groupParam === "status" || groupParam === "type" || groupParam === "agent"
      ? groupParam
      : "none";

  const orderParam = asString(resolvedSearchParams.order);
  const order: "name" | "status" | "next" =
    orderParam === "status" || orderParam === "next" ? orderParam : "name";

  const search = asString(resolvedSearchParams.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateTriggerButton />,
      }}
      className="overflow-hidden p-0"
    >
      <Suspense
        key={`${view}-${tab}-${group}-${order}-${search}`}
        fallback={
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <TriggersContent initial={{ view, tab, group, order, search }} />
      </Suspense>
    </ContentBlock>
  );
}
