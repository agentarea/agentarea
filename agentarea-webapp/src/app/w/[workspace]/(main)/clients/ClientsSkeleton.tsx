import ContentBlock from "@/components/ContentBlock";
import { CollectionSkeleton, type SkeletonColumn } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";

const CLIENTS_GRID_CLASS =
  "grid grid-cols-1 gap-[12px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";

function ClientCardSkeleton() {
  return (
    <div className="card card-shadow group flex min-h-[150px] flex-col gap-3 p-4">
      <Skeleton className="h-5 w-2/3 motion-reduce:animate-none" />
      <Skeleton className="h-3 w-full motion-reduce:animate-none" />
      <Skeleton className="mt-auto h-3 w-1/2 motion-reduce:animate-none" />
    </div>
  );
}

export default function ClientsSkeleton({
  title,
  description,
  viewMode,
}: {
  title: string;
  description: string;
  viewMode?: string;
}) {
  const columns: SkeletonColumn[] = [
    { barClassName: "h-7 w-40 motion-reduce:animate-none" },
    { barClassName: "w-20 motion-reduce:animate-none" },
    { barClassName: "w-24 motion-reduce:animate-none" },
    { barClassName: "w-24 motion-reduce:animate-none" },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: title }],
        description,
        controls: <Skeleton className="h-8 w-24 motion-reduce:animate-none" />,
      }}
    >
      <div aria-hidden="true">
        <div className="mb-3 flex items-center justify-end">
          <Skeleton className="h-7 w-28 motion-reduce:animate-none" />
        </div>
        <CollectionSkeleton
          viewMode={viewMode}
          columns={columns}
          rows={8}
          gridClassName={CLIENTS_GRID_CLASS}
          count={10}
          Card={ClientCardSkeleton}
        />
      </div>
    </ContentBlock>
  );
}
