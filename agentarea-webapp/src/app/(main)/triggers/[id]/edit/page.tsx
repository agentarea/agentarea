import { getTrigger, listAgents } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { CreateTriggerForm } from "../../create/CreateTriggerForm";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditTriggerPage({ params }: Props) {
  const { id } = await params;

  const [triggerResponse, agentsResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
  ]);

  const trigger = requireApiData(triggerResponse, "trigger");

  return (
    <div className="p-6">
      <CreateTriggerForm
        agents={(agentsResponse.data as any[]) || []}
        initialData={trigger}
      />
    </div>
  );
}
