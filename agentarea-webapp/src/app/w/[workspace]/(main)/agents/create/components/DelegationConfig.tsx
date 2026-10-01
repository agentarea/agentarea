"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";
import AccordionControl from "@/components/AccordionControl";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { ResourcePicker } from "@/components/ResourcePicker/ResourcePicker";
import { Button } from "@/components/ui/button";
import Note from "@/components/ui/note";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { listAgentsAction } from "@/lib/server-actions";

const AgentIcon = ENTITY_ICONS.agent;

type DelegateAgent = {
  id: string;
  name: string;
  description?: string | null;
};

type DelegationConfigProps = {
  /** The agent being edited, left out of its own delegates; absent on create. */
  agentId?: string;
  /** Names of the agents this agent may delegate to. */
  delegates: string[];
  onDelegatesChange: (delegates: string[]) => void;
};

export default function DelegationConfig({
  agentId,
  delegates,
  onDelegatesChange,
}: DelegationConfigProps) {
  const t = useTranslations("AgentsPage.delegationConfig");
  const [accordionValue, setAccordionValue] = useState("delegation");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [agents, setAgents] = useState<DelegateAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listAgentsAction()
      .then((result) => {
        if (cancelled) return;
        if (result.error || !result.data) {
          console.error("Failed to load agents for delegation", result.error);
          setFailed(true);
          return;
        }
        setAgents(result.data.filter((agent) => agent.id !== agentId));
        setFailed(false);
      })
      .catch((err) => {
        console.error("Failed to load agents for delegation", err);
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, revision]);

  const byName = useMemo(
    () => new Map(agents.map((agent) => [agent.name, agent])),
    [agents]
  );
  const selectedIds = delegates.flatMap((name) => {
    const agent = byName.get(name);
    return agent ? [agent.id] : [];
  });

  const add = (agent: DelegateAgent) => {
    if (delegates.includes(agent.name)) return;
    onDelegatesChange([...delegates, agent.name]);
  };
  const remove = (name: string) =>
    onDelegatesChange(delegates.filter((delegate) => delegate !== name));

  return (
    <AccordionControl
      id="delegation"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={AgentIcon} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={t("note")}
      mainControl={
        <ConfigSheet
          title={t("title")}
          description={t("sheetDescription")}
          triggerText={t("add")}
          className="ml-auto"
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
        >
          <div className="flex flex-col space-y-4 overflow-y-auto">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <AgentIcon className="h-4 w-4 text-muted-foreground" />
              {t("available")}
            </div>
            <ResourcePicker
              items={agents}
              prefix="delegate"
              selectedIds={selectedIds}
              onAdd={add}
              onRemove={(agent) => remove(agent.name)}
              loading={loading}
              failed={failed}
              onRefresh={() => setRevision((n) => n + 1)}
              emptyText={t("noOtherAgents")}
              manageText={t("createAgent")}
              manageHref="/agents/create"
              extractTitle={(agent) => (
                <span className="flex items-center gap-2">
                  <AgentIcon className="h-4 w-4" />
                  {agent.name}
                </span>
              )}
            />
          </div>
        </ConfigSheet>
      }
    >
      {delegates.length > 0 ? (
        <ul className="divide-y divide-border rounded-md border">
          {delegates.map((name) => (
            <li key={name} className="flex items-center gap-2 px-3 py-2">
              <AgentIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{name}</p>
                {byName.get(name)?.description && (
                  <p className="truncate text-xs text-muted-foreground">
                    {byName.get(name)?.description}
                  </p>
                )}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => remove(name)}
                className="h-4 w-4 shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                aria-label={t("remove", { name })}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
          <p>{t("empty")}</p>
        </Note>
      )}
    </AccordionControl>
  );
}
