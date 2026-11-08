"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { AgentResponse } from "@/api/client/types.gen";
import AccordionControl from "@/components/AccordionControl";
import { AgentAvatar } from "@/components/AgentAvatar";
import FormLabel from "@/components/FormLabel/FormLabel";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import Note from "@/components/ui/note";
import Link from "@/components/WorkspaceLink";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { agentPath } from "@/types";

/** The agents whose turns run on this client's runner. */
export function ClientAgents({ agents }: { agents: AgentResponse[] }) {
  const t = useTranslations("ClientsPage.agents");
  const [open, setOpen] = useState("client-agents");

  return (
    <AccordionControl
      id="client-agents"
      accordionValue={open}
      setAccordionValue={setOpen}
      title={
        <FormLabel icon={ENTITY_ICONS.agent} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={<p>{t("description")}</p>}
      noteInline
      count={agents.length}
      mainControl={null}
    >
      {agents.length > 0 ? (
        <div className="mt-2 overflow-hidden rounded-md border border-border/60">
          {agents.map((agent) => (
            <Link key={agent.id} href={agentPath(agent)} className="block">
              <InteractiveListRow
                className="px-[15px] py-[11px]"
                dividerClassName="border-b border-border/60 last:border-b-0"
                start={<AgentAvatar agent={agent} size="sm" />}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-medium">
                    {agent.name}
                  </div>
                  {agent.description && (
                    <div className="mt-px truncate text-[11px] text-muted-foreground">
                      {agent.description}
                    </div>
                  )}
                </div>
              </InteractiveListRow>
            </Link>
          ))}
        </div>
      ) : (
        <Note className="mt-2">
          <p>{t("empty")}</p>
        </Note>
      )}
    </AccordionControl>
  );
}
