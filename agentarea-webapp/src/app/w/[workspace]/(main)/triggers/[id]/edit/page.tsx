import type { Metadata } from "next";
import type { AgentResponse, TriggerResponse } from "@/api/client/types.gen";
import { getTrigger, listAgents } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { CreateTriggerForm } from "../../create/CreateTriggerForm";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const trigger = requireApiData<TriggerResponse>(
    await getTrigger(id),
    "trigger"
  );
  return { title: trigger.name ? `Edit ${trigger.name}` : "Edit trigger" };
}

/** Changing a saved automation reuses the form that created it.
 *
 * The overview owns the read: schedule, health, last runs. This route owns the
 * write, so one screen never has to be both.
 */
export default async function EditTriggerPage({ params }: Props) {
  const { id } = await params;

  const [triggerResponse, agentsResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
  ]);

  const trigger = requireApiData<TriggerResponse>(triggerResponse, "trigger");
  const agents: AgentResponse[] = agentsResponse.data ?? [];

  return (
    <div className="px-4 py-5">
      <div className="mx-auto w-full max-w-5xl">
        <CreateTriggerForm agents={agents} initialData={trigger} />
      </div>
    </div>
  );
}
