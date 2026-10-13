import { getTranslations } from "next-intl/server";
import type { ExecutionHistoryResponse } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import OffsetPagination from "@/components/OffsetPagination";
import { getTriggerExecutions, resolvePrincipals } from "@/lib/api";
import { pageHref, parsePageParam } from "@/lib/offsetPage";
import ExecutionsTable from "./ExecutionsTable";

const EXECUTIONS_PAGE_SIZE = 20;

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

  const path = `/triggers/${id}/executions`;
  const page = parsePageParam(resolvedSearchParams.page);
  if (page === null) {
    return (
      <div className="p-6">
        <RetryEmptyState
          title={t("noExecutionsOnPage")}
          iconsType="triggers"
          additionAction={{
            label: t("firstPage"),
            href: pageHref(path, resolvedSearchParams, 1),
          }}
        />
      </div>
    );
  }

  const { data, error } = await getTriggerExecutions(id, {
    page,
    page_size: EXECUTIONS_PAGE_SIZE,
  });

  if (error || !data) {
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
  const { executions, has_next: hasNext } = data as ExecutionHistoryResponse;

  if (executions.length === 0 && page === 1) {
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

  // Past the last page, e.g. from a stale link after history was trimmed.
  if (executions.length === 0) {
    return (
      <div className="p-6">
        <RetryEmptyState
          title={t("noExecutionsOnPage")}
          iconsType="triggers"
          additionAction={{
            label: t("firstPage"),
            href: pageHref(path, resolvedSearchParams, 1),
          }}
        />
      </div>
    );
  }

  // fired_by is an id; the name is resolved here rather than stored on the
  // execution, so a person who is renamed is renamed everywhere at once.
  const principals = await resolvePrincipals([
    ...new Set(
      executions
        .map((execution) => execution.fired_by)
        .filter((id): id is string => Boolean(id))
    ),
  ]);
  const principalNames = Object.fromEntries(
    (principals.data ?? [])
      .filter((principal) => principal.display_name)
      .map((principal) => [principal.id, principal.display_name as string])
  );

  return (
    <div className="p-6">
      <ExecutionsTable
        executions={executions}
        principalNames={principalNames}
      />
      <OffsetPagination
        path={path}
        page={page}
        hasNext={hasNext}
        searchParams={resolvedSearchParams}
      />
    </div>
  );
}
