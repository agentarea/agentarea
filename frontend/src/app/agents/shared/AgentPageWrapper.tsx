import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
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
}

export default async function AgentPageWrapper({ 
  children, 
  breadcrumb, 
  useContentBlock = true,
  className = "h-full w-full px-4 py-5"
}: AgentPageWrapperProps) {
  const t = await getTranslations("AgentsPage");

  const content = (
    <Suspense fallback={
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner />
      </div>
    }>
      {children}
    </Suspense>
  );

  if (useContentBlock) {
    return (
      <ContentBlock 
        header={{
          breadcrumb: breadcrumb.map(item => ({
            label: item.label,
            href: item.href
          }))
        }}
      >
        {content}
      </ContentBlock>
    );
  }

  return (
    <div className={className}>
      {content}
    </div>
  );
}
