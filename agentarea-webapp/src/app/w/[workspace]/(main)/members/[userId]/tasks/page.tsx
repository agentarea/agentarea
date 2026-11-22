import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import { TasksData } from "../../../tasks/components/TasksData";
import { getMemberCached } from "../memberDetail";

interface Props {
  params: Promise<{ userId: string }>;
}

/** Every task this member started, drawn by the workspace task list. */
export default async function MemberTasksPage({ params }: Props) {
  const { userId } = await params;
  const [{ member, currentUser, label }, uiPrefs, t] = await Promise.all([
    getMemberCached(userId),
    readUiPrefs(),
    getTranslations("MembersPage.detail"),
  ]);
  const isSelf = member.user_id === currentUser.id;

  return (
    <div className="h-full overflow-y-auto px-4 py-5">
      <TasksData
        query={{ statuses: [], search: "", creator: member.user_id }}
        viewMode={uiPrefs.views["tab_tasks"] || "table"}
        empty={
          <EmptyState
            title={isSelf ? t("noTasksSelf") : t("noTasksOther")}
            description={
              isSelf ? undefined : t("noTasksOtherHint", { member: label })
            }
            iconsType="tasks"
          />
        }
      />
    </div>
  );
}
