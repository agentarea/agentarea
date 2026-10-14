import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import ExecutionsInfiniteList from "./ExecutionsInfiniteList";
import { loadExecutionsPage } from "./executionsPage";

interface Props {
  params: Promise<{ id: string }>;
}

/** A trigger's runs, newest first; further pages load as the list scrolls. */
export default async function TriggerExecutionsPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage.detail");

  const firstPage = await loadExecutionsPage(id, 1);

  if (!firstPage) {
    return (
      <div className="p-6">
        <RetryEmptyState
          title={t("executionsLoadFailed")}
          iconsType="triggers"
          additionAction={{
            label: t("overview"),
            href: `/triggers/${id}`,
          }}
        />
      </div>
    );
  }

  if (firstPage.executions.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          title={t("noExecutions")}
          description={t("noExecutionsDescription")}
          iconsType="triggers"
        />
      </div>
    );
  }

  return (
    <div className="p-6">
      <ExecutionsInfiniteList triggerId={id} firstPage={firstPage} />
    </div>
  );
}
