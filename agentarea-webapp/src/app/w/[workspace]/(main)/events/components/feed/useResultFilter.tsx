"use client";

import { useTranslations } from "next-intl";
import { ListFilter } from "lucide-react";
import type { ToolbarSelectProps } from "@/components/ToolbarSelect";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { PROCESSING_RESULTS, type FeedState } from "@/lib/eventFeed";
import { getEventProcessingStatusPresentation } from "@/lib/status";

const ALL = "all";

/**
 * The "result" select of a feed's subheader (what the platform did with an
 * event), shared by the workspace feed and a stream's page.
 */
export function useResultFilter(
  state: FeedState,
  go: (patch: Partial<FeedState>) => void
): Pick<ToolbarSelectProps<string>, "label" | "groups" | "value" | "onChange"> {
  const t = useTranslations("EventsPage");
  return {
    label: t("list.result"),
    groups: [
      [
        {
          value: ALL,
          label: t("result.all"),
          // Unfiltered, the button names the filter (as Linear does).
          triggerLabel: t("list.result"),
          icon: <ListFilter className="h-3.5 w-3.5" />,
        },
      ],
      PROCESSING_RESULTS.map((result) => {
        const presentation = getEventProcessingStatusPresentation(result);
        return {
          value: result,
          label: t(`result.${presentation.labelKey}`),
          icon: (
            <StatusIndicator
              size="sm"
              kind={presentation.kind}
              aria-hidden="true"
            />
          ),
        };
      }),
    ],
    value: state.result ?? ALL,
    onChange: (value) =>
      go({ result: PROCESSING_RESULTS.find((r) => r === value) }),
  };
}
