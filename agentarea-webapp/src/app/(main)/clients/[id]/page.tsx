"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Link as LinkIcon, Loader2, Pencil, Terminal } from "lucide-react";
import { toast } from "sonner";
import type {
  ClientResponse,
  McpServerInstanceResponse,
  McpServerResponse,
  SkillResponse,
} from "@/api/client";
import { getMCPConnectionIconSrc } from "@/app/(main)/connections/utils";
import {
  AttachmentSection,
  hydrateAttachments,
  type AttachmentItem,
} from "@/components/AttachmentSection";
import ContentBlock from "@/components/ContentBlock";
import DeleteButton from "@/components/DeleteButton";
import FormLabel from "@/components/FormLabel/FormLabel";
import { DetailSkeleton } from "@/components/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  addMcpInstanceToClientAction,
  addSkillToClientAction,
  deleteClientAction,
  getClientAction,
  listMCPServerInstancesAction,
  listMCPServersAction,
  listSkillsAction,
  removeMcpInstanceFromClientAction,
  removeSkillFromClientAction,
  updateClientAction,
} from "@/lib/server-actions";
import { HARNESS_LABELS, harnessOf } from "../harnesses";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

export default function ClientDetailPage() {
  const params = useParams();
  const clientId = params.id as string;

  const [client, setClient] = useState<ClientResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [allSkills, setAllSkills] = useState<SkillResponse[]>([]);
  const [allMcp, setAllMcp] = useState<McpServerInstanceResponse[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerResponse[]>([]);

  const [showEdit, setShowEdit] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchClient = useCallback(async () => {
    const { data } = await getClientAction(clientId);
    if (data) setClient(data);
  }, [clientId]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [clientRes, skillsRes, mcpRes, serversRes] = await Promise.all([
          getClientAction(clientId),
          listSkillsAction(),
          listMCPServerInstancesAction(),
          listMCPServersAction({ page_size: 100 }),
        ]);
        if (clientRes.data) setClient(clientRes.data);
        setAllSkills((skillsRes.data as SkillResponse[]) || []);
        setAllMcp(mcpRes.data || []);
        const serversData = serversRes.data as
          | { items?: McpServerResponse[] }
          | McpServerResponse[]
          | undefined;
        setMcpServers(
          Array.isArray(serversData) ? serversData : serversData?.items || []
        );
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [clientId]);

  if (loading) return <DetailSkeleton />;
  if (!client) return null;

  const harness = harnessOf(client.kind);
  const HarnessGlyph = harness.icon;

  const instanceIconSrc = (instance: AttachmentItem) => {
    const full = allMcp.find((i) => String(i.id) === instance.id);
    if (!full) return undefined;
    const spec = mcpServers.find((s) => s.id === full.server_spec_id);
    return getMCPConnectionIconSrc(full, spec);
  };

  const handleSave = async () => {
    if (!editName.trim()) return;
    setSaving(true);
    try {
      const { error } = await updateClientAction(clientId, {
        name: editName.trim(),
        description: editDescription || null,
      });
      if (error) {
        toast.error("Failed to update client");
        return;
      }
      setShowEdit(false);
      await fetchClient();
    } finally {
      setSaving(false);
    }
  };

  const syncCmd = `agentarea mcp sync --client=${clientId} --target=${
    client.kind === "harness" ? "codex" : client.kind
  }`;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Clients", href: "/clients" },
          { label: client.name },
        ],
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                setEditName(client.name);
                setEditDescription(client.description || "");
                setShowEdit(true);
              }}
            >
              <Pencil className="h-4 w-4" />
              Edit
            </Button>
            <DeleteButton
              size="xs"
              itemId={clientId}
              itemName={client.name}
              onDelete={deleteClientAction}
              redirectPath="/clients"
              title="Delete Client"
              description={`Delete "${client.name}"? The scoped MCP endpoint stops working for any harness connected to it. This cannot be undone.`}
              successMessage="Client deleted"
            />
          </div>
        ),
      }}
    >
      <div className="mx-auto w-full max-w-4xl overflow-auto p-4 sm:p-6">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border/60 bg-background text-muted-foreground">
            <HarnessGlyph aria-hidden="true" className="h-5 w-5" />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">
                {client.name}
              </h2>
              <Badge variant="outline" className="text-xs">
                {harness.label}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {client.description ||
                "A governed, scoped tool bundle an external harness connects to over MCP."}
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {client.mcp_endpoint_url && (
            <div className="space-y-1.5">
              <FormLabel icon={LinkIcon}>MCP endpoint</FormLabel>
              <CopyableText text={client.mcp_endpoint_url} />
            </div>
          )}
          <div className="space-y-1.5">
            <FormLabel icon={Terminal}>Sync command</FormLabel>
            <CopyableText text={syncCmd} />
          </div>
        </div>

        <Divider />

        <AttachmentSection
          id="client-mcp"
          title="MCP Servers"
          icon={McpIcon}
          note={
            <p>
              Instances exposed through this client&apos;s endpoint. Tools keep
              the namespace prefix set on the instance.
            </p>
          }
          triggerText="MCP Server"
          sheetTitle="MCP Servers"
          sheetDescription="Add MCP server instances to this client's bundle"
          availableTitle="Active MCP Server Instances"
          attached={hydrateAttachments(client.mcp_instances, allMcp)}
          available={allMcp}
          emptyLabel="No MCP servers connected. Add one to expose its tools through the endpoint."
          emptyAvailable={
            <p>
              No MCP server instances yet. Create one under Connections first.
            </p>
          }
          onAdd={(item) => addMcpInstanceToClientAction(clientId, item.id)}
          onRemove={(item) =>
            removeMcpInstanceFromClientAction(clientId, item.id)
          }
          onChanged={fetchClient}
          getIconSrc={instanceIconSrc}
        />

        <Divider />

        <AttachmentSection
          id="client-skills"
          title="Skills"
          icon={SkillIcon}
          note={
            <p>
              Skills reachable through the endpoint&apos;s `activate_skill`
              tool.
            </p>
          }
          triggerText="Skill"
          sheetTitle="Skills"
          sheetDescription="Add skills to this client's bundle"
          availableTitle="Available Skills"
          attached={hydrateAttachments(client.skills, allSkills)}
          available={allSkills}
          emptyLabel="No skills connected. Add skills the harness should be able to activate."
          emptyAvailable={<p>No skills available. Create one under Skills.</p>}
          onAdd={(item) => addSkillToClientAction(clientId, item.id)}
          onRemove={(item) => removeSkillFromClientAction(clientId, item.id)}
          onChanged={fetchClient}
        />
      </div>

      <Dialog open={showEdit} onOpenChange={setShowEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Client</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-name" required>
                Name
              </FormLabel>
              <Input
                id="client-name"
                placeholder="my-codex"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-description" optional>
                Description
              </FormLabel>
              <Textarea
                id="client-description"
                placeholder={`What this ${HARNESS_LABELS[client.kind] ?? "harness"} connection is for`}
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowEdit(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!editName.trim() || saving}
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
