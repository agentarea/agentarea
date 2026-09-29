import { redirect } from "next/navigation";
import { workspacePath } from "@/lib/workspace-routes";

interface Props {
  params: Promise<{ workspace: string; id: string }>;
}

export default async function TaskMetricsPage({ params }: Props) {
  const { workspace, id } = await params;
  redirect(workspacePath(workspace, `/tasks/${id}`));
}
