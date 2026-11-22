"use client";

import { useTranslations } from "next-intl";
import {
  Activity,
  Inbox,
  LayoutDashboard,
  StickyNote,
  Table2,
  Workflow,
} from "lucide-react";
import EntityMark from "@/components/EntityMark";
import { TaskStatus } from "@/components/TaskStatus";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import type { TileInput } from "../utils/canvasState";
import type { CanvasData } from "./canvasTypes";

export type CanvasTemplate = "org" | "apps";

const ICON = "h-4 w-4 text-muted-foreground";

export default function AddTileDialog({
  open,
  onOpenChange,
  data,
  onAdd,
  onTemplate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  data: CanvasData;
  onAdd: (input: TileInput) => void;
  onTemplate: (template: CanvasTemplate) => void;
}) {
  const t = useTranslations("CanvasPage");
  const close = () => onOpenChange(false);
  const add = (input: TileInput) => {
    onAdd(input);
    close();
  };
  const AgentIcon = ENTITY_ICONS.agent;

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("addTitle")}
    >
      <CommandInput placeholder={t("searchPlaceholder")} />
      <CommandList>
        <CommandEmpty>{t("searchEmpty")}</CommandEmpty>
        <CommandGroup heading={t("groupTemplates")}>
          <CommandItem
            value={`template ${t("templateOrg")}`}
            onSelect={() => {
              onTemplate("org");
              close();
            }}
          >
            <Workflow className={ICON} />
            {t("templateOrg")}
          </CommandItem>
          <CommandItem
            value={`template ${t("templateApps")}`}
            onSelect={() => {
              onTemplate("apps");
              close();
            }}
          >
            <LayoutDashboard className={ICON} />
            {t("templateApps")}
          </CommandItem>
        </CommandGroup>
        {data.apps.length > 0 && (
          <CommandGroup heading={t("groupApps")}>
            {data.apps.map((app) => (
              <CommandItem
                key={app.id}
                value={`app ${app.title} ${app.connectionTitle} ${app.id}`}
                onSelect={() => add({ kind: "app", appId: app.id })}
              >
                <EntityMark
                  identity={app.identity}
                  className="h-4 w-4 shrink-0 rounded-[3px]"
                />
                <span className="truncate">{app.title}</span>
                <span className="ml-auto truncate text-xs text-muted-foreground">
                  {app.connectionTitle}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        <CommandGroup heading={t("groupViews")}>
          <CommandItem
            value={`feed ${t("feedActive")}`}
            onSelect={() => add({ kind: "feed", feed: "active" })}
          >
            <Activity className={ICON} />
            {t("feedActive")}
          </CommandItem>
          <CommandItem
            value={`feed ${t("feedAttention")}`}
            onSelect={() => add({ kind: "feed", feed: "attention" })}
          >
            <Inbox className={ICON} />
            {t("feedAttention")}
          </CommandItem>
          <CommandItem
            value={`table ${t("tableTasks")}`}
            onSelect={() => add({ kind: "table", source: "tasks" })}
          >
            <Table2 className={ICON} />
            {t("tableTasks")}
          </CommandItem>
          <CommandItem
            value={`table ${t("tableSpend")}`}
            onSelect={() => add({ kind: "table", source: "agentSpend" })}
          >
            <Table2 className={ICON} />
            {t("tableSpend")}
          </CommandItem>
          <CommandItem
            value={`note ${t("note")}`}
            onSelect={() => add({ kind: "note", text: "" })}
          >
            <StickyNote className={ICON} />
            {t("note")}
          </CommandItem>
        </CommandGroup>
        {data.agents.length > 0 && (
          <CommandGroup heading={t("groupAgents")}>
            {data.agents.map((agent) => (
              <CommandItem
                key={agent.id}
                value={`agent ${agent.name} ${agent.id}`}
                onSelect={() => add({ kind: "agent", agentId: agent.id })}
              >
                <AgentIcon className={ICON} />
                <span className="truncate">{agent.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {data.tasks.length > 0 && (
          <CommandGroup heading={t("groupTasks")}>
            {data.tasks.slice(0, 30).map((task) => (
              <CommandItem
                key={task.id}
                value={`task ${task.title} ${task.agentName ?? ""} ${task.id}`}
                onSelect={() =>
                  add({
                    kind: "task",
                    taskId: task.id,
                    agentId: task.agentId,
                    title: task.title,
                  })
                }
              >
                <TaskStatus status={task.status} caption="never" />
                <span className="truncate">{task.title}</span>
                {task.agentName && (
                  <span className="ml-auto shrink-0 truncate text-xs text-muted-foreground">
                    {task.agentName}
                  </span>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {data.connections.length > 0 && (
          <CommandGroup heading={t("groupConnections")}>
            {data.connections.map((connection) => (
              <CommandItem
                key={connection.id}
                value={`connection ${connection.title} ${connection.id}`}
                onSelect={() =>
                  add({ kind: "connection", connectionId: connection.id })
                }
              >
                <EntityMark
                  identity={connection.identity}
                  className="h-4 w-4 shrink-0 rounded-[3px]"
                />
                <span className="truncate">{connection.title}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
