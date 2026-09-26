"use client";

import { useLayoutEffect } from "react";
import { useTranslations } from "next-intl";
import {
  Handle,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import type { NetworkPerson } from "@/api/client/types.gen";
import { EntityIcon } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";

export function visiblePeople(
  people: NetworkPerson[],
  selectedId: string | null
) {
  const selected = people.find((person) => person.user_id === selectedId);
  const visible = people.slice(0, 4);
  if (selected && !visible.includes(selected)) visible[3] = selected;
  return visible;
}
export function peopleRosterHeight(count: number) {
  return 84 + Math.max(1, Math.min(4, count)) * 44;
}
export type PeopleStatus = "loading" | "ready" | "error";
export interface NetworkPeopleNodeData extends Record<string, unknown> {
  status: PeopleStatus;
  people: NetworkPerson[];
  selectedId: string | null;
  total: number;
  totalKnown: boolean;
  directoryDisabled: boolean;
  onSelect: (id: string) => void;
  onDirectory: () => void;
  onRetry: () => void;
}
export default function NetworkPeopleNode({
  id,
  data,
}: NodeProps<Node<NetworkPeopleNodeData>>) {
  const t = useTranslations("NetworkPage.people");
  const people = visiblePeople(data.people, data.selectedId);
  const update = useUpdateNodeInternals();
  const signature = people.map((person) => person.user_id).join("|");
  useLayoutEffect(() => {
    update(id);
  }, [id, signature, data.status, update]);
  return (
    <div className="h-full w-60 rounded-lg border border-border bg-background shadow-sm">
      <header className="flex h-[47px] items-center gap-2 border-b border-border px-3">
        <EntityIcon kind="person" className="h-4 w-4 text-primary" />
        <span className="flex-1 text-xs font-semibold">{t("title")}</span>
        {data.status === "ready" && (
          <span className="text-xs tabular-nums text-muted-foreground">
            {data.totalKnown ? data.total : data.total ? `≥${data.total}` : "?"}
          </span>
        )}
      </header>
      {data.status === "ready" && people.length > 0 ? (
        people.map((person, index) => (
          <div key={person.user_id}>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                data.onSelect(person.user_id);
              }}
              onKeyDown={(event) => event.stopPropagation()}
              title={person.email ?? person.user_id}
              className={cn(
                "nodrag nopan flex h-11 w-full items-center gap-2 px-3 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
                person.user_id === data.selectedId && "bg-primary/10"
              )}
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                <EntityIcon
                  kind="person"
                  className="h-3.5 w-3.5 text-muted-foreground"
                />
              </span>
              <span className="min-w-0 truncate text-xs">
                {person.display_name ||
                  person.email ||
                  t("unnamed", { id: person.user_id.slice(0, 8) })}
              </span>
            </button>
            <Handle
              id={`person:${person.user_id}`}
              type="source"
              position={Position.Right}
              isConnectable={false}
              style={{ top: 48 + index * 44 + 22 }}
              className="!h-1.5 !w-1.5 !border-background !bg-primary"
            />
          </div>
        ))
      ) : (
        <p
          className="flex h-11 items-center px-3 text-[11px] text-muted-foreground"
          role="status"
        >
          {t(
            data.status === "loading"
              ? "loading"
              : data.status === "error"
                ? "unavailableShort"
                : data.directoryDisabled
                  ? "unknownRoster"
                  : "empty"
          )}
        </p>
      )}
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          data.status === "error" ? data.onRetry() : data.onDirectory();
        }}
        onKeyDown={(event) => event.stopPropagation()}
        className="nodrag nopan flex h-[35px] w-full items-center rounded-b-lg border-t border-border px-3 text-[11px] font-medium text-primary hover:bg-muted focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        {t(data.status === "error" ? "retry" : "directory")}
      </button>
    </div>
  );
}
