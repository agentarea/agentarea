"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { ClientResponse } from "@/api/client/types.gen";
import { Plus, Loader2, Bot, Terminal, Plug, type LucideIcon } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { ENTITY_ICONS, EntityIcon } from "@/lib/entity-icons";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

// Harness kinds a client can represent. `kind` is set at creation and updated by
// `agentarea mcp sync --target=<harness>`.
const HARNESSES: Record<string, { label: string; icon: LucideIcon }> = {
  claude: { label: "Claude Code", icon: Bot },
  "claude-code": { label: "Claude Code", icon: Bot },
  codex: { label: "Codex", icon: Terminal },
  harness: { label: "Generic", icon: Plug },
};

function harnessOf(kind?: string | null) {
  return HARNESSES[kind ?? ""] ?? { label: kind || "Generic", icon: Plug };
}

function HarnessBadge({ kind }: { kind?: string | null }) {
  const { label, icon: Icon } = harnessOf(kind);
  return (
    <Badge variant="outline" className="gap-1 text-xs">
      <Icon className="h-3 w-3" />
      {label}
    </Badge>
  );
}

function NameChips({
  items,
}: {
  items?: { id: string; name: string }[] | null;
}) {
  const list = items ?? [];
  if (!list.length)
    return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {list.slice(0, 3).map((i) => (
        <Badge key={i.id} variant="secondary" className="max-w-[120px] truncate text-[10px]">
          {i.name}
        </Badge>
      ))}
      {list.length > 3 && (
        <span className="text-[10px] text-muted-foreground">
          +{list.length - 3}
        </span>
      )}
    </div>
  );
}
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import {
  listClientsAction,
  createClientAction,
} from "@/lib/server-actions";

export default function ClientsPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState("harness");
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listClientsAction();
      setClients((data as ClientResponse[]) || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const { error } = await createClientAction({ name: name.trim(), description: description || null, kind });
      if (error) {
        toast({ title: "Error", description: "Failed to create client", variant: "destructive" });
        return;
      }
      setShowCreate(false);
      setName("");
      setDescription("");
      setKind("harness");
      await load();
    } finally {
      setCreating(false);
    }
  };

  const columns = [
    {
      header: "Client",
      accessor: "name",
      render: (name: string, client: ClientResponse) => (
        <div className="flex items-center gap-2">
          <EntityIcon kind="client" className="text-primary" />
          <div>
            <div className="font-medium">{name}</div>
            {client.description && (
              <div className="mt-1 max-w-md text-xs text-muted-foreground line-clamp-1">
                {client.description}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      header: "Harness",
      accessor: "kind",
      render: (value: string) => <HarnessBadge kind={value} />,
    },
    {
      header: "MCP",
      accessor: "mcp_instances",
      render: (value: ClientResponse["mcp_instances"]) => (
        <NameChips items={value} />
      ),
    },
    {
      header: "Skills",
      accessor: "skills",
      render: (value: ClientResponse["skills"]) => <NameChips items={value} />,
    },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Clients" }],
        description: "Agent-proxies: scoped MCP + skill bundles for external harnesses (codex, claude-code)",
        controls: (
          <Button className="shrink-0 gap-2" size="xs" onClick={() => setShowCreate(true)}>
            <Plus className="h-5 w-5" />
            New Client
          </Button>
        ),
      }}
    >
      <div className="p-6">
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <GridAndTableViews
            searchParams={{ tab: searchParams.get("tab") ?? undefined }}
            routeChange="/clients"
            data={clients}
            columns={columns}
            itemLink={(client: ClientResponse) => `/clients/${client.id}`}
            emptyState={
              <EmptyState
                title="No clients yet"
                description="Create one to give an external harness a governed, scoped tool bundle."
                iconsType="mcp"
              />
            }
            cardContent={(client: ClientResponse) => (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-[16px] font-[500]">
                  <EntityIcon kind="client" className="text-primary" />
                  {client.name}
                </div>
                {client.description && (
                  <div className="line-clamp-2 pt-[6px] text-[14px] opacity-50">
                    {client.description}
                  </div>
                )}
                <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <McpIcon className="h-3.5 w-3.5" />
                    {client.mcp_instances?.length ?? 0}
                  </span>
                  <span className="flex items-center gap-1">
                    <SkillIcon className="h-3.5 w-3.5" />
                    {client.skills?.length ?? 0}
                  </span>
                  <span className="ml-auto">
                    <HarnessBadge kind={client.kind} />
                  </span>
                </div>
              </div>
            )}
          />
        )}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Client</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <input
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              placeholder="Name (e.g. my-codex)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <textarea
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              placeholder="Description (optional)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Harness</label>
              <select
                className="w-full rounded border bg-background px-3 py-2 text-sm"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="harness">Generic</option>
                <option value="claude">Claude Code</option>
                <option value="codex">Codex</option>
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={!name.trim() || creating}>
              {creating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
