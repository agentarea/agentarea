import { getTranslations } from "next-intl/server";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { pageHref } from "@/lib/offsetPage";

interface OffsetPaginationProps {
  /** Workspace-relative path of the paged list, e.g. "/tasks". */
  path: string;
  page: number;
  hasNext: boolean;
  /** The page's own search parameters, kept on every link but `page`. */
  searchParams: Record<string, string | string[] | undefined>;
}

/** Previous / page N / next links under a list paged with `?page=`. */
export default async function OffsetPagination({
  path,
  page,
  hasNext,
  searchParams,
}: OffsetPaginationProps) {
  if (page === 1 && !hasNext) return null;
  const t = await getTranslations("Common");

  return (
    <nav className="flex items-center justify-center gap-2 py-4">
      {page > 1 ? (
        <Button asChild variant="outline" size="sm">
          <Link href={pageHref(path, searchParams, page - 1)}>
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
          <Link href={pageHref(path, searchParams, page + 1)}>
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
