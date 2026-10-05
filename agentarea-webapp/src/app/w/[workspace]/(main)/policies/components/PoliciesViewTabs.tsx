"use client";

import { useTranslations } from "next-intl";
import { Network, ShieldCheck } from "lucide-react";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";

type PoliciesView = "policies" | "access";

const TABS: { value: PoliciesView; icon: typeof ShieldCheck }[] = [
  { value: "policies", icon: ShieldCheck },
  { value: "access", icon: Network },
];

/**
 * Policies / Access switch of the policies page subheader. Two sections of the
 * page rather than a filter over one list, so it takes the solid pill, like
 * the Models sections.
 */
export function PoliciesViewTabs({ current }: { current: PoliciesView }) {
  const t = useTranslations("PoliciesPage.tabs");
  const router = useWorkspaceRouter();

  return (
    <CountSegmentedControl<PoliciesView>
      items={TABS.map(({ value, icon: Icon }) => ({
        value,
        label: (
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <Icon className="h-4 w-4" />
            {t(value)}
          </span>
        ),
      }))}
      value={current}
      onChange={(next) =>
        router.push(next === "policies" ? "/policies" : "/policies?view=access")
      }
      variant="solid"
      layoutId="policies-view-control"
    />
  );
}
