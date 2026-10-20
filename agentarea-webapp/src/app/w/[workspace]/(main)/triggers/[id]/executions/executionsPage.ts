import type {
  ExecutionHistoryResponse,
  TriggerExecutionResponse,
} from "@/api/client/types.gen";
import { getTriggerExecutions, resolvePrincipals } from "@/lib/api";

export const EXECUTIONS_PAGE_SIZE = 20;

export type ExecutionsPage = {
  executions: TriggerExecutionResponse[];
  hasNext: boolean;
  /** Principal id -> display name, for the people who pressed "run now". */
  principalNames: Record<string, string>;
};

/** One page of a trigger's runs, newest first, with who fired the manual ones. */
export async function loadExecutionsPage(
  triggerId: string,
  page: number
): Promise<ExecutionsPage | null> {
  const { data, error } = await getTriggerExecutions(triggerId, {
    page,
    page_size: EXECUTIONS_PAGE_SIZE,
  });
  if (error || !data) return null;
  const { executions, has_next: hasNext } = data as ExecutionHistoryResponse;

  // fired_by is an id; the name is resolved here rather than stored on the
  // execution, so a person who is renamed is renamed everywhere at once.
  const ids = [
    ...new Set(
      executions
        .map((execution) => execution.fired_by)
        .filter((id): id is string => Boolean(id))
    ),
  ];
  const principals = ids.length ? await resolvePrincipals(ids) : null;
  const principalNames = Object.fromEntries(
    (principals?.data ?? [])
      .filter((principal) => principal.display_name)
      .map((principal) => [principal.id, principal.display_name as string])
  );

  return { executions, hasNext, principalNames };
}
