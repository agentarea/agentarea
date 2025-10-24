import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from 'next-intl/server';
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { TasksData } from "./components/TasksData";
import SearchInput from "@/components/SearchInput";
import TasksHeaderTabs from "./components/TasksHeaderTabs";
import { cookies } from 'next/headers';

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const t = await getTranslations("TasksPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery = typeof resolvedSearchParams.search === 'string' ? resolvedSearchParams.search : "";
  
  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get('tab_tasks')?.value;
  const tab = typeof resolvedSearchParams.tab === 'string' ? resolvedSearchParams.tab : (cookieTab || "grid");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          {label: t("title")},
        ],
      }}
      subheader={
        <>
          <SearchInput 
            urlParamName="search"
            urlPath="/tasks"
          />
          <TasksHeaderTabs />
        </>
      }
    >
      <Suspense 
        key={`${searchQuery}-${tab}`}
        fallback={
          <div className="flex items-center justify-center h-32">
            <LoadingSpinner />
          </div>
        }
      >
        <TasksData searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
