import type { Metadata } from "next";
import { Link as LinkIcon } from "lucide-react";
import type { AgentResponse, TriggerResponse } from "@/api/client/types.gen";
import { CopyableText } from "@/components/ui/copyable-text";
import { getTrigger, listAgents } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { CreateTriggerForm } from "../create/CreateTriggerForm";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const trigger = requireApiData<TriggerResponse>(
    await getTrigger(id),
    "trigger"
  );
  return { title: trigger.name ?? "Trigger" };
}

/** A saved automation opens in the same form that created it.
 *
 * It used to open a read-only summary with a separate /edit page rendering the
 * form, which meant two screens describing one thing and a click between
 * looking and changing. The webhook URL rides above it because the form has no
 * field for a value the server assigns.
 */
export default async function TriggerPage({ params }: Props) {
  const { id } = await params;

  const [triggerResponse, agentsResponse] = await Promise.all([
    getTrigger(id),
    listAgents(),
  ]);

  const trigger = requireApiData<TriggerResponse>(triggerResponse, "trigger");
  const agents: AgentResponse[] = agentsResponse.data ?? [];
  const webhookUrl = (trigger as { webhook_url?: string }).webhook_url;

  return (
    <div className="px-4 py-5">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        {trigger.trigger_type !== "cron" && webhookUrl && (
          <div className="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
            <div className="flex items-center gap-2">
              <LinkIcon className="h-4 w-4 text-muted-foreground" />
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Webhook URL
              </span>
            </div>
            <CopyableText text={webhookUrl} />
          </div>
        )}
        <CreateTriggerForm agents={agents} initialData={trigger} />
      </div>
    </div>
  );
}
