import ContentBlock from "@/components/ContentBlock";
import { FileBrowserSkeleton } from "@/components/files/file-browser-skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function FilesSkeleton({ title }: { title: string }) {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: title }],
        // The upload button.
        controls: <Skeleton className="h-6 w-36 motion-reduce:animate-none" />,
      }}
      className="min-h-0 overflow-hidden p-0"
    >
      <FileBrowserSkeleton />
    </ContentBlock>
  );
}
