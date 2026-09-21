import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import { Badge } from "@/components/ui/badge";
import TasksConcept from "./TasksConcept";

export const metadata: Metadata = {
  title: "Tasks · Concept",
};

export default function TasksConceptPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Tasks", href: "/tasks" }, { label: "Concept" }],
        controls: (
          <Badge
            variant="amber"
            size="sm"
            className="max-w-[12rem] whitespace-normal text-right leading-4"
          >
            Demo data · 18 Sep 2026 · 09:00 UTC
          </Badge>
        ),
      }}
      className="!p-0"
    >
      <TasksConcept />
    </ContentBlock>
  );
}
