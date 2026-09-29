"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { TaskStatus } from "@/components/TaskStatus";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import {
  filterValueFor,
  TASK_STATUS_FILTER_OPTIONS,
} from "@/lib/taskStatusFilter";

const ALL = "all";

export default function TasksStatusFilter() {
  const t = useTranslations("TasksFilters");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const onChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === ALL) params.delete("status");
    else params.set("status", value);
    params.delete("page");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };

  const selected = searchParams.get("status");

  return (
    <Select
      value={(selected && filterValueFor(selected)) || ALL}
      onValueChange={onChange}
    >
      <SelectTrigger
        aria-label={t("filterByStatus")}
        className="h-8 w-auto min-w-[150px] border-border bg-transparent px-2.5 text-[12.5px] shadow-none"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectItem value={ALL}>{t("allStatuses")}</SelectItem>
        {TASK_STATUS_FILTER_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            <TaskStatus status={option.value} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
