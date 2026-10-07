"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { ListFilter } from "lucide-react";
import { TaskStatus } from "@/components/TaskStatus";
import ToolbarSelect from "@/components/ToolbarSelect";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import {
  filterValueFor,
  TASK_STATUS_FILTER_GROUPS,
  TASK_STATUS_FILTER_OPTIONS,
} from "@/lib/taskStatusFilter";

const ALL = "all";

/** Status filter of the task list, in the subheader. Drives `?status=`. */
export default function TasksStatusFilter() {
  const t = useTranslations("TasksFilters");
  const tStatus = useTranslations("TasksPage.status");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const onChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === ALL) params.delete("status");
    else params.set("status", value);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };

  const selected = searchParams.get("status");

  // All statuses, then work in flight, then what waits on a person, then what
  // is over. Every row carries a 14px glyph, the size DisplayMenu rows use, so
  // the labels line up.
  return (
    <ToolbarSelect
      label={t("filterByStatus")}
      value={(selected && filterValueFor(selected)) || ALL}
      onChange={onChange}
      groups={[
        [
          {
            value: ALL,
            label: t("allStatuses"),
            icon: <ListFilter className="h-3.5 w-3.5 text-muted-foreground" />,
          },
        ],
        ...TASK_STATUS_FILTER_GROUPS.map((group) =>
          TASK_STATUS_FILTER_OPTIONS.filter(
            (option) => option.group === group
          ).map((option) => ({
            value: option.value,
            label: option.labelKey ? tStatus(option.labelKey) : option.label,
            icon: (
              <TaskStatus
                status={option.value}
                size="default"
                caption="never"
              />
            ),
          }))
        ),
      ]}
    />
  );
}
