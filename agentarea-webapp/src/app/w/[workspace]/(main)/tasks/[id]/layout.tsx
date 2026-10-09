import { getTranslations } from "next-intl/server";
import type { TaskRequester } from "@/components/TaskInfoPanel/types";
import { getTask, resolvePrincipals } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import TaskLayoutClient from "./TaskLayoutClient";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

/**
 * The person `created_by` names, for the Participants panel. The viewer's own
 * token names them when the directory has no display name for them yet.
 */
async function resolveRequester(
  userId: string | null | undefined
): Promise<TaskRequester | null> {
  if (!userId) return null;
  // A name is not worth failing the task page over: unresolved, the panel
  // labels the person as unknown.
  const [principals, auth] = await Promise.all([
    resolvePrincipals([userId]).catch(() => null),
    getAuthContext(),
  ]);
  const isCurrentUser = auth.userId === userId;
  const name =
    principals?.data?.find((principal) => principal.id === userId)
      ?.display_name ||
    (isCurrentUser ? auth.name || auth.email || auth.username : null);
  return { id: userId, name: name || null, isCurrentUser };
}

export default async function TaskLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TasksPage");

  // Fetch task server-side — no client loading spinner needed
  const result = await getTask(id);
  const requester = await resolveRequester(result.data?.created_by);

  return (
    <TaskLayoutClient
      taskId={id}
      tasksTitle={t("title")}
      initialTask={result.data ?? null}
      initialError={
        result.error ? apiErrorMessage(result, "Failed to load task") : null
      }
      requester={requester}
    >
      {children}
    </TaskLayoutClient>
  );
}
