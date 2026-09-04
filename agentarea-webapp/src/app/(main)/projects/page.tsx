import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import ProjectsContent from "./components/ProjectsContent";
import ProjectsSkeleton from "./components/ProjectsSkeleton";

export const metadata: Metadata = {
  title: "Projects",
};

interface ProjectsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProjectsPage({ searchParams }: ProjectsPageProps) {
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Projects" }],
        description: "Organize agents, skills, and tools into projects",
        controls: (
          <Link href="/projects/create">
            <Button className="shrink-0" size="xs">
              <Plus />
              New Project
            </Button>
          </Link>
        ),
      }}
      subheader={
        <SearchInput urlParamName="search" urlPath="/projects" />
      }
    >
      <Suspense key={searchQuery} fallback={<ProjectsSkeleton />}>
        <ProjectsContent
          searchQuery={searchQuery}
          searchParams={resolvedSearchParams}
        />
      </Suspense>
    </ContentBlock>
  );
}
