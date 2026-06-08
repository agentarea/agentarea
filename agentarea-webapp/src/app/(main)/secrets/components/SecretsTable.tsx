"use client";

import { useMemo } from "react";
import { KeyRound } from "lucide-react";
import CollectionView, {
  type CollectionItem,
  shortAge,
} from "@/components/CollectionView";

type MCPInstance = {
  id: string;
  name: string;
  auth_type?: string | null;
  status?: string | null;
  created_at?: string | null;
};

function statusColor(status?: string | null): string | undefined {
  if (!status) return undefined;
  const s = status.toLowerCase();
  if (/(active|success|succeed|healthy|connected|ready)/.test(s)) return "#27a08c";
  if (/(fail|error|unhealthy|denied)/.test(s)) return "#d6453d";
  if (/(progress|pending|connecting)/.test(s)) return "#d99a00";
  return "#8a8f98";
}

export function SecretsTable({ instances }: { instances: MCPInstance[] }) {
  const items = useMemo<CollectionItem[]>(
    () =>
      instances.map((inst) => ({
        id: inst.id,
        icon: KeyRound,
        color: "#5e6ad2",
        title: inst.name,
        href: `/mcp-servers/${inst.id}`,
        badges: [
          { label: inst.auth_type ?? "None" },
          ...(inst.status
            ? [{ label: inst.status, color: statusColor(inst.status) }]
            : []),
        ],
        meta: shortAge(inst.created_at),
      })),
    [instances]
  );

  return <CollectionView view="list" items={items} bleed />;
}
