import { getTranslations } from "next-intl/server";
import TasksSkeleton from "@/app/(main)/tasks/components/TasksSkeleton";

export default async function Loading() {
  const t = await getTranslations("TasksPage");

  // Mirrors the table on this route: the agent column is dropped, since every
  // row belongs to the agent the page is already about.
  const columns = [
    { header: t("statusLabel"), barClassName: "h-5 w-20 rounded-full" },
    { header: t("description"), barClassName: "h-4 w-48" },
    { header: t("source"), barClassName: "h-4 w-24" },
    { header: t("cost"), barClassName: "h-4 w-12" },
    { header: t("created"), barClassName: "h-8 w-24" },
  ];

  return (
    <div className="h-full overflow-auto px-4 py-5">
      <TasksSkeleton viewMode="table" columns={columns} />
    </div>
  );
}
