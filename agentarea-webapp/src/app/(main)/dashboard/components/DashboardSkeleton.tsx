import { useTranslations } from "next-intl";
import { Activity, Bot, Shield, Wallet } from "lucide-react";
import { BoardGrid, BoardSectionHeader } from "@/components/board";
import { Skeleton } from "@/components/ui/skeleton";

function SpendSkeleton() {
  const t = useTranslations("DashboardPage");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Wallet />}
        color="hsl(var(--chart-2))"
        title={t("spend")}
        meta={t("monthToDate")}
      />
      <div className="mt-1.5 flex items-start gap-3.5">
        <div>
          <Skeleton className="h-7 w-28" />
          <Skeleton className="mt-2 h-3.5 w-24" />
        </div>
        <div className="ml-auto flex flex-col items-end gap-1.5">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="mt-1 h-[5px] w-[150px] rounded-full" />
        </div>
      </div>
      <Skeleton className="-mx-6 mt-3 flex-1 rounded-none" />
    </div>
  );
}

function ActivitySkeleton() {
  const t = useTranslations("DashboardPage");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Activity />}
        color="hsl(var(--violet))"
        title={t("activity")}
        meta={t("activityMeta")}
      />
      <div className="mt-2.5 flex flex-1 flex-col gap-2 sm:grid sm:grid-cols-3 lg:flex lg:flex-col lg:gap-1.5">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="flex min-h-[46px] flex-1 items-center gap-3.5 rounded-[9px] border px-3.5 py-2"
          >
            <div className="flex min-w-[120px] flex-col gap-1.5">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-5 w-10" />
            </div>
            <Skeleton className="hidden h-6 flex-1 lg:block" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ListSkeleton({
  icon,
  color,
  title,
  rows,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  rows: number;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pb-3 pt-4">
        <BoardSectionHeader icon={icon} color={color} title={title} pill="…" />
      </div>
      <div className="min-h-0 flex-1">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 border-b border-border/60 px-6 py-3"
          >
            <Skeleton className="h-9 w-9 shrink-0 rounded-md" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-48" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DashboardSkeleton() {
  const t = useTranslations("DashboardPage");
  return (
    <div aria-hidden="true" className="h-full">
      <BoardGrid
        topLeft={<SpendSkeleton />}
        topRight={<ActivitySkeleton />}
        bottomLeft={
          <ListSkeleton
            icon={<Bot />}
            color="hsl(var(--primary))"
            title={t("agents")}
            rows={5}
          />
        }
        bottomRight={
          <ListSkeleton
            icon={<Shield />}
            color="hsl(var(--chart-4))"
            title={t("blockers")}
            rows={4}
          />
        }
      />
    </div>
  );
}
