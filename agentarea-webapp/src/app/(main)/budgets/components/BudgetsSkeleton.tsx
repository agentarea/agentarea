import { useTranslations } from "next-intl";
import { Gauge, Wallet } from "lucide-react";
import { BoardSectionHeader } from "@/components/board";
import { Skeleton } from "@/components/ui/skeleton";
import { BudgetsBoard } from "./BudgetsBoard";

function SpendSkeleton() {
  const t = useTranslations("DashboardPage");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Wallet />}
        color="hsl(var(--foreground))"
        title={t("spend")}
        meta={t("monthToDate")}
      />
      <div className="mt-1 flex items-start gap-3.5">
        <div>
          <Skeleton className="h-6 w-24" />
          <Skeleton className="mt-1.5 h-3.5 w-24" />
        </div>
        <div className="ml-auto flex flex-col items-end gap-1.5">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="mt-1 h-[5px] w-[168px] rounded-full" />
        </div>
      </div>
      <Skeleton className="-mx-6 mt-1 min-h-[132px] flex-1 rounded-none" />
    </div>
  );
}

function OutlookSkeleton() {
  const t = useTranslations("BudgetsPage");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Gauge />}
        color="hsl(var(--foreground))"
        title={t("monthOutlook")}
        meta={t("currentPeriod")}
      />
      <div className="mt-3.5 flex flex-col">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="flex items-baseline justify-between gap-4 border-b border-dashed py-4 [border-color:var(--board-line)] last:border-0"
          >
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-3.5 w-28" />
              <Skeleton className="h-3 w-36" />
            </div>
            <Skeleton className="h-5 w-16" />
          </div>
        ))}
      </div>
      <Skeleton className="mt-3.5 h-3.5 w-full" />
    </div>
  );
}

function CapSkeleton() {
  return (
    <section className="grid items-start gap-x-8 gap-y-6 rounded-xl border border-border bg-background p-5 md:grid-cols-[minmax(0,1fr)_300px]">
      <div className="flex gap-3.5 md:col-start-1">
        <Skeleton className="h-[38px] w-[38px] rounded-[10px]" />
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-64" />
        </div>
      </div>
      <div className="flex flex-col gap-2.5 md:col-start-2 md:row-span-2 md:row-start-1">
        <Skeleton className="h-3.5 w-32" />
        <div className="flex gap-2.5">
          <Skeleton className="h-[38px] flex-1 rounded-md" />
          <Skeleton className="h-[38px] w-16 rounded-md" />
        </div>
      </div>
      <div className="md:col-start-1 md:row-start-2">
        <div className="flex items-baseline justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-28" />
        </div>
        <Skeleton className="mt-2.5 h-[7px] w-full rounded-full" />
      </div>
    </section>
  );
}

export default function BudgetsSkeleton() {
  return (
    <div aria-hidden="true" className="h-full">
      <BudgetsBoard
        spend={<SpendSkeleton />}
        outlook={<OutlookSkeleton />}
        capCard={<CapSkeleton />}
      />
    </div>
  );
}
