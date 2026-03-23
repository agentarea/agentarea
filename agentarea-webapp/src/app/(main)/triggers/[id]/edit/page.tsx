import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock";
import { getTrigger, listAgents } from "@/lib/api";
import { CreateTriggerForm } from "../../create/CreateTriggerForm";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditTriggerPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage");

  const [triggerResponse, agentsResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
  ]);

  const trigger = triggerResponse.data;
  if (!trigger) notFound();

  return (
    <div className="p-6">
      <CreateTriggerForm
        agents={(agentsResponse.data as any[]) || []}
        initialData={trigger}
      />
    </div>
  );
}
