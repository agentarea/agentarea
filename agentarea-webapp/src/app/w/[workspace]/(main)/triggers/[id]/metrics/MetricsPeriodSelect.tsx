"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { CalendarClock } from "lucide-react";
import ToolbarSelect from "@/components/ToolbarSelect";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import {
  DEFAULT_METRICS_PERIOD,
  METRICS_PERIODS,
  parseMetricsPeriod,
  type MetricsPeriod,
} from "./period";

/** The metrics tab's window, in the subheader. Drives `?period=`. */
export default function MetricsPeriodSelect() {
  const t = useTranslations("TriggersPage.detail");
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const onChange = (value: MetricsPeriod) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === DEFAULT_METRICS_PERIOD) params.delete("period");
    else params.set("period", value);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };

  return (
    <ToolbarSelect
      label={t("metricsPeriod")}
      icon={<CalendarClock className="h-3.5 w-3.5" />}
      value={parseMetricsPeriod(searchParams.get("period"))}
      onChange={onChange}
      groups={[
        METRICS_PERIODS.map((period) => ({
          value: period,
          label: t(`periodOption.${period}`),
        })),
      ]}
    />
  );
}
