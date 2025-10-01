import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from 'next-intl/server';
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { TasksData } from "./components/TasksData";
import SearchInput from "@/components/SearchInput";

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const t = await getTranslations("TasksPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery = typeof resolvedSearchParams.search === 'string' ? resolvedSearchParams.search : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          {label: t("title")},
        ],
      }}
      className="p-0"
    >
      <div className="flex flex-col h-full">
        <div className="bg-white dark:bg-zinc-800 px-4 border-b border-zinc-200 dark:border-zinc-700">
        <SearchInput 
          urlParamName="search"
          urlPath="/tasks"
        />
        </div>
        <div className="px-4 py-5 overflow-auto h-full">
          <Suspense 
            key={searchQuery}
            fallback={
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            }
          >
            <TasksData searchQuery={searchQuery} />
          </Suspense>
        </div>
      </div>
    </ContentBlock>
  );
}