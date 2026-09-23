"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import type { ClientResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import FormLabel from "@/components/FormLabel/FormLabel";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { createClientAction, listClientsAction } from "@/lib/server-actions";
import { HARNESS_OPTIONS, HarnessBadge, HarnessIcon } from "./harnesses";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

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
        <Badge
          key={i.id}
          variant="secondary"
          className="max-w-[120px] truncate text-[10px]"
        >
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

export default function ClientsPage() {
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
      const { error } = await createClientAction({
        name: name.trim(),
        description: description || null,
        kind,
      });
      if (error) {
        toast.error("Failed to add harness");
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
      header: "Harness",
      accessor: "name",
      render: (name: string, client: ClientResponse) => (
        <div className="flex items-center gap-2">
          <HarnessIcon
            kind={client.kind}
            className="h-5 w-5 shrink-0 text-primary"
          />
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
      header: "Type",
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
        breadcrumb: [{ label: "Harnesses" }],
        description:
          "Connect external agent harnesses to your workspace's tools and skills.",
        controls: (
          <Button className="shrink-0" size="xs" onClick={() => setShowCreate(true)}>
            <Plus />
            Add harness
          </Button>
        ),
      }}
    >
      <div>
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
                title="No harnesses yet"
                description="A harness is a coding agent running outside this workspace — Claude Code, Codex — that you let reach in for tools."
                hints={[
                  { text: "Register the harness to get its connection command" },
                  { text: "Pick the skills and connections it may use" },
                  { text: "It gets that bundle and nothing else" },
                ]}
                iconsType="mcp"
                action={{
                  label: "Add harness",
                  onClick: () => setShowCreate(true),
                }}
              />
            }
            cardContent={(client: ClientResponse) => {
              const mcpCount = client.mcp_instances?.length ?? 0;
              const skillCount = client.skills?.length ?? 0;
              return (
                <div className="flex h-full flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <HarnessIcon
                        kind={client.kind}
                        className="h-5 w-5 shrink-0 text-muted-foreground"
                      />
                      <h3 className="truncate text-[15px] font-medium leading-tight tracking-tight">
                        {client.name}
                      </h3>
                    </div>
                    <HarnessBadge kind={client.kind} />
                  </div>
                  {client.description && (
                    <p className="line-clamp-2 text-sm text-muted-foreground">
                      {client.description}
                    </p>
                  )}
                  {/* Counts say what they count. A bare "0 / 2" beside two
                      glyphs asked the reader to decode the icons first. */}
                  <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <McpIcon className="h-3.5 w-3.5" />
                      {mcpCount === 1 ? "1 connection" : `${mcpCount} connections`}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <SkillIcon className="h-3.5 w-3.5" />
                      {skillCount === 1 ? "1 skill" : `${skillCount} skills`}
                    </span>
                  </div>
                </div>
              );
            }}
          />
        )}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add harness</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-name" required>
                Name
              </FormLabel>
              <Input
                id="new-client-name"
                placeholder="my-codex"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-description" optional>
                Description
              </FormLabel>
              <Textarea
                id="new-client-description"
                placeholder="What this connection is for"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-kind">Type</FormLabel>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger id="new-client-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HARNESS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={!name.trim() || creating}>
              {creating ? <Loader2 className="mr-2 animate-spin" /> : null}
              Add harness
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
