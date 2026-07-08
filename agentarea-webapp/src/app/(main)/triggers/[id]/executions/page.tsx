import { getTranslations } from "next-intl/server";
import type { ExecutionHistoryResponse } from "@/api/client/types.gen";
import { getTriggerExecutions } from "@/lib/api";
import ExecutionsTable from "./ExecutionsTable";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function TriggerExecutionsPage({
  params,
  searchParams,
}: Props) {
  const { id } = await params;
  const resolvedSearchParams = await searchParams;
  const t = await getTranslations("TriggersPage.detail");

  const page =
    typeof resolvedSearchParams.page === "string"
      ? parseInt(resolvedSearchParams.page, 10)
      : 1;

  const { data, error } = await getTriggerExecutions(id, {
    page,
    page_size: 20,
  });

  if (error || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        Failed to load executions
      </div>
    );
  }

  const executions = (data as ExecutionHistoryResponse).executions;

  if (executions.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center p-6">
        <p className="text-lg font-medium text-muted-foreground">
          {t("noExecutions")}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("noExecutionsDescription")}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <ExecutionsTable
        executions={executions}
        triggerId={id}
        currentPage={page}
      />
    </div>
  );
}
