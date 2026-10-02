import { useTranslations } from "next-intl";
import { CalendarDays, ListChecks, Shield, Wallet } from "lucide-react";
import { BoardGrid, BoardSectionHeader } from "@/components/board";
import { Skeleton } from "@/components/ui/skeleton";

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
      <Skeleton className="-mx-6 mt-1 h-[188px] rounded-none" />
    </div>
  );
}

function CalendarSkeleton() {
  const t = useTranslations("DashboardPage");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pb-3 pt-4">
        <BoardSectionHeader
          icon={<CalendarDays />}
          color="hsl(var(--foreground))"
          title={t("schedule")}
        />
      </div>
      <Skeleton className="m-4 mt-0 flex-1 rounded-md" />
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
            className="flex items-center gap-3 border-b border-zinc-200 px-6 py-3 dark:border-zinc-700"
          >
            <Skeleton className="h-6 w-6 shrink-0 rounded-md" />
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
        topRight={
          <ListSkeleton
            icon={<Shield />}
            color="hsl(var(--foreground))"
            title={t("blockers")}
            rows={3}
          />
        }
        topRightPadded={false}
        bottomLeft={<CalendarSkeleton />}
        bottomRight={
          <ListSkeleton
            icon={<ListChecks />}
            color="hsl(var(--foreground))"
            title={t("tasks")}
            rows={5}
          />
        }
      />
    </div>
  );
}
