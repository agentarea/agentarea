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
      subheader={
        <SearchInput 
          urlParamName="search"
          urlPath="/tasks"
        />
      }
    >
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
    </ContentBlock>
  );
}