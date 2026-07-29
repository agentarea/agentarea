import { FileText, LayoutDashboard, Settings } from "lucide-react";
import { ActiveLink } from "@/components/ui/active-link";

export default function ProjectHeaderTabs({
  projectId,
}: {
  projectId: string;
}) {
  return (
    <nav
      aria-label="Project sections"
      className="inline-flex items-center gap-0.5 rounded-lg bg-muted/60 p-1"
    >
      <ActiveLink
        href={`/projects/${projectId}`}
        className="rounded-md border-b-0 px-2.5 py-1.5 font-medium hover:bg-background/70 aria-[current=page]:bg-background aria-[current=page]:shadow-sm"
      >
        <LayoutDashboard className="h-4 w-4" />
        Overview
      </ActiveLink>
      <ActiveLink
        href={`/projects/${projectId}/files`}
        className="rounded-md border-b-0 px-2.5 py-1.5 font-medium hover:bg-background/70 aria-[current=page]:bg-background aria-[current=page]:shadow-sm"
      >
        <FileText className="h-4 w-4" />
        Files
      </ActiveLink>
      <ActiveLink
        href={`/projects/${projectId}/settings`}
        className="rounded-md border-b-0 px-2.5 py-1.5 font-medium hover:bg-background/70 aria-[current=page]:bg-background aria-[current=page]:shadow-sm"
      >
        <Settings className="h-4 w-4" />
        Settings
      </ActiveLink>
    </nav>
  );
}
