import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Gauge, Wallet } from "lucide-react";
import { BoardColumns, BoardSectionHeader } from "@/components/board";
import { Skeleton } from "@/components/ui/skeleton";
import { EntityIcon } from "@/lib/entity-icons";

function Header({
  icon,
  title,
  meta,
}: {
  icon: ReactNode;
  title: string;
  meta?: string;
}) {
  return (
    <BoardSectionHeader
      icon={icon}
      color="hsl(var(--foreground))"
      title={title}
      meta={meta}
    />
  );
}

export default function BudgetsSkeleton() {
  const t = useTranslations("BudgetsPage");
  const tDash = useTranslations("DashboardPage");
  return (
    <div aria-hidden="true" className="h-full">
      <BoardColumns
        leftFraction={0.6}
        left={[
          <div key="spend" className="px-8 pb-6 pt-5">
            <Header
              icon={<Wallet />}
              title={tDash("spend")}
              meta={tDash("monthToDate")}
            />
            <Skeleton className="mt-2 h-7 w-32" />
            <Skeleton className="mt-2 h-3.5 w-56" />
            <Skeleton className="mt-3 h-[190px] w-full" />
          </div>,
          <div key="agents" className="flex flex-col gap-3 px-8 pb-6 pt-5">
            <Header
              icon={<EntityIcon kind="agent" />}
              title={t("agentsTitle")}
              meta={tDash("monthToDate")}
            />
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>,
        ]}
        right={[
          <div key="money" className="px-8 pb-6 pt-5">
            <Header icon={<Gauge />} title={t("monthlyCap")} />
            <Skeleton className="mt-2 h-7 w-32" />
            <Skeleton className="mt-2 h-3.5 w-56" />
            <Skeleton className="mt-5 h-[7px] w-full rounded-full" />
          </div>,
        ]}
      />
    </div>
  );
}
