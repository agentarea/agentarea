import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import TableSkeleton from "@/components/Skeleton/TableSkeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { ToolbarDivider } from "@/components/ui/toolbar";

// Shown while the members page fetches on the server. Keeps the real
// breadcrumb; the toolbar counts, section copy and table need data and are
// skeletoned in the same shape the loaded page takes.
export default async function MembersSkeleton() {
  const t = await getTranslations("MembersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <Skeleton className="h-8 w-[118px] rounded-md" />,
      }}
      subheader={
        <div className="flex flex-1 items-center gap-1.5" aria-hidden="true">
          <Skeleton className="h-7 w-[104px] rounded-md" />
          <Skeleton className="h-7 w-[116px] rounded-md" />
          <ToolbarDivider />
          <Skeleton className="h-5 w-[200px]" />
        </div>
      }
    >
      <section className="space-y-3" aria-hidden="true">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-3 w-[420px] max-w-full" />
        </div>
        <TableSkeleton
          rows={5}
          columns={[
            { header: t("member"), barClassName: "h-7 w-52" },
            {
              header: t("accessColumn"),
              headerClassName: "w-[180px]",
              barClassName: "h-5 w-16 rounded-full",
            },
            { headerClassName: "w-0", barClassName: "h-7 w-7" },
          ]}
        />
      </section>
    </ContentBlock>
  );
}
