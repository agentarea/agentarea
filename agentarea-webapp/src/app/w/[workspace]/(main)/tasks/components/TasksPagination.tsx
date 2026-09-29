import { getTranslations } from "next-intl/server";
import Link from "@/components/WorkspaceLink";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { pageHref } from "@/lib/offsetPage";

interface TasksPaginationProps {
  page: number;
  hasNext: boolean;
  searchParams: Record<string, string | string[] | undefined>;
}

export default async function TasksPagination({
  page,
  hasNext,
  searchParams,
}: TasksPaginationProps) {
  if (page === 1 && !hasNext) return null;
  const t = await getTranslations("TasksPage");

  return (
    <nav className="flex items-center justify-center gap-2 py-4">
      {page > 1 ? (
        <Button asChild variant="outline" size="sm">
          <Link href={pageHref("/tasks", searchParams, page - 1)}>
            <ChevronLeft />
            {t("previousPage")}
          </Link>
        </Button>
      ) : (
        <Button variant="outline" size="sm" disabled>
          <ChevronLeft />
          {t("previousPage")}
        </Button>
      )}
      <span className="text-sm tabular-nums">{t("pageNumber", { page })}</span>
      {hasNext ? (
        <Button asChild variant="outline" size="sm">
          <Link href={pageHref("/tasks", searchParams, page + 1)}>
            {t("nextPage")}
            <ChevronRight />
          </Link>
        </Button>
      ) : (
        <Button variant="outline" size="sm" disabled>
          {t("nextPage")}
          <ChevronRight />
        </Button>
      )}
    </nav>
  );
}
