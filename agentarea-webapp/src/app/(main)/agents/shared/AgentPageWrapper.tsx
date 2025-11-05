import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface AgentPageWrapperProps {
  children: React.ReactNode;
  breadcrumb: BreadcrumbItem[];
  useContentBlock?: boolean;
  className?: string;
  controls?: React.ReactNode;
}

export default async function AgentPageWrapper({
  children,
  breadcrumb,
  useContentBlock = true,
  className = "h-full w-full px-4 py-5",
  controls,
}: AgentPageWrapperProps) {
  const t = await getTranslations("AgentsPage");

  const content = (
    <Suspense
      fallback={
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      {children}
    </Suspense>
  );

  if (useContentBlock) {
    return (
      <ContentBlock
        header={{
          breadcrumb: breadcrumb.map((item) => ({
            label: item.label,
            href: item.href,
          })),
          controls,
        }}
      >
        {content}
      </ContentBlock>
    );
  }

  return <div className={className}>{content}</div>;
}
