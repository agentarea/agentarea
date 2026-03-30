import { FileText, Settings, LayoutDashboard } from "lucide-react";
import { ActiveLink } from "@/components/ui/active-link";

export default function ProjectHeaderTabs({ projectId }: { projectId: string }) {
  return (
    <div className="inline-flex items-center gap-3 py-2">
      <ActiveLink href={`/projects/${projectId}`}>
        <LayoutDashboard className="h-4 w-4" />
        Overview
      </ActiveLink>
      <ActiveLink href={`/projects/${projectId}/files`}>
        <FileText className="h-4 w-4" />
        Files
      </ActiveLink>
      <ActiveLink href={`/projects/${projectId}/settings`}>
        <Settings className="h-4 w-4" />
        Settings
      </ActiveLink>
    </div>
  );
}
