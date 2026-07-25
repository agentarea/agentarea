"use client";

import {
  useEffect,
  useState,
  type ComponentType,
  type SVGProps,
} from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Check,
  Copy,
  Link as LinkIcon,
  Loader2,
  Pencil,
  Plug,
  Plus,
  Terminal,
  Trash2,
} from "lucide-react";
import { ClaudeIcon, CodexIcon } from "@/components/brand-icons";
import ContentBlock from "@/components/ContentBlock";
import { DetailSkeleton } from "@/components/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import type {
  ClientResponse,
  ClientRef,
  SkillResponse,
  McpServerInstanceResponse,
  ProjectResponse,
} from "@/api/client";
import {
  getClientAction,
  updateClientAction,
  deleteClientAction,
  addSkillToClientAction,
  removeSkillFromClientAction,
  addMcpInstanceToClientAction,
  removeMcpInstanceFromClientAction,
  pullClientFromProjectAction,
  listSkillsAction,
  listMCPServerInstancesAction,
  listProjectsAction,
} from "@/lib/server-actions";

type HarnessIcon = ComponentType<SVGProps<SVGSVGElement>>;

const HARNESSES: Record<string, { label: string; icon: HarnessIcon }> = {
  claude: { label: "Claude Code", icon: ClaudeIcon },
  "claude-code": { label: "Claude Code", icon: ClaudeIcon },
  codex: { label: "Codex", icon: CodexIcon },
  harness: { label: "Generic", icon: Plug },
};

function harnessOf(kind?: string | null) {
  return HARNESSES[kind ?? ""] ?? { label: kind || "Generic", icon: Plug };
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast({ title: `Copied ${label ?? "value"}` });
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast({ title: "Copy failed", variant: "destructive" });
    }
  };
  return (
    <Button
      variant="outline"
      size="xs"
      onClick={handleCopy}
      aria-label={`Copy ${label ?? "value"}`}
    >
      {copied ? (
        <Check className="h-4 w-4 text-green-500" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );
}

interface ScopeSectionProps {
  title: string;
  kind: Extract<EntityKind, "mcp" | "skill">;
  emptyLabel: string;
  items: ClientRef[];
  allItems: { id: string; name: string }[];
  onAdd: (id: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  addLabel: string;
  placeholder: string;
}

function ScopeSection({
  title,
  kind,
  emptyLabel,
  items,
  allItems,
  onAdd,
  onRemove,
  addLabel,
  placeholder,
}: ScopeSectionProps) {
  const { toast } = useToast();
  const [showAdd, setShowAdd] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const available = allItems.filter(
    (a) => !items.some((i) => String(i.id) === a.id)
  );

  const handleAdd = async () => {
    if (!selectedId) return;
    setAdding(true);
    try {
      await onAdd(selectedId);
      setShowAdd(false);
      setSelectedId("");
    } catch {
      toast({ title: "Error", description: `Failed to add`, variant: "destructive" });
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    try {
      await onRemove(id);
    } catch {
      toast({ title: "Error", description: "Failed to remove", variant: "destructive" });
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <EntityIcon kind={kind} className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
            {items.length}
          </span>
        </div>
        <Button size="xs" variant="outline" onClick={() => setShowAdd(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          {addLabel}
        </Button>
      </div>

      {items.length === 0 ? (
        <p className="note py-2">{emptyLabel}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li
              key={String(item.id)}
              className="group flex items-center justify-between gap-2 rounded-md border border-border/60 bg-background px-3 py-2 text-sm"
            >
              <span className="min-w-0 truncate">{item.name}</span>
              <Button
                size="xs"
                variant="ghost"
                aria-label={`Remove ${item.name}`}
                className="shrink-0 text-muted-foreground hover:text-destructive"
                onClick={() => handleRemove(String(item.id))}
                disabled={removingId === String(item.id)}
              >
                {removingId === String(item.id) ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{addLabel}</DialogTitle>
          </DialogHeader>
          <div className="py-2">
            {available.length === 0 ? (
              <p className="note">Nothing left to add.</p>
            ) : (
              <select
                aria-label={placeholder}
                className="w-full rounded-md border bg-background text-foreground [color-scheme:light] dark:[color-scheme:dark] px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                <option value="">{placeholder}</option>
                {available.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleAdd}
              disabled={!selectedId || adding || available.length === 0}
            >
              {adding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default function ClientDetailPage() {
  const params = useParams();
  const router = useRouter();
  const clientId = params.id as string;
  const { toast } = useToast();

  const [client, setClient] = useState<ClientResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [allSkills, setAllSkills] = useState<SkillResponse[]>([]);
  const [allMcp, setAllMcp] = useState<McpServerInstanceResponse[]>([]);
  const [allProjects, setAllProjects] = useState<ProjectResponse[]>([]);

  const [showEdit, setShowEdit] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fetchClient = async () => {
    const { data } = await getClientAction(clientId);
    if (data) setClient(data);
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [clientRes, skillsRes, mcpRes, projectsRes] = await Promise.all([
          getClientAction(clientId),
          listSkillsAction(),
          listMCPServerInstancesAction(),
          listProjectsAction(),
        ]);
        if (clientRes.data) setClient(clientRes.data);
        setAllSkills((skillsRes.data as SkillResponse[]) || []);
        setAllMcp(mcpRes.data || []);
        setAllProjects(projectsRes.data || []);
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
  const sourceProject = allProjects.find(
    (p) => p.id === client.source_project_id
  );

  const handleAddMcp = async (id: string) => {
    const { error } = await addMcpInstanceToClientAction(clientId, id);
    if (error) throw error;
    toast({ title: "MCP instance added" });
    await fetchClient();
  };
  const handleRemoveMcp = async (id: string) => {
    const { error } = await removeMcpInstanceFromClientAction(clientId, id);
    if (error) throw error;
    toast({ title: "MCP instance removed" });
    await fetchClient();
  };
  const handleAddSkill = async (id: string) => {
    const { error } = await addSkillToClientAction(clientId, id);
    if (error) throw error;
    toast({ title: "Skill added" });
    await fetchClient();
  };
  const handleRemoveSkill = async (id: string) => {
    const { error } = await removeSkillFromClientAction(clientId, id);
    if (error) throw error;
    toast({ title: "Skill removed" });
    await fetchClient();
  };

  const handlePull = async (projectId: string) => {
    const { error } = await pullClientFromProjectAction(
      clientId,
      projectId || null
    );
    if (error) {
      toast({
        title: "Error",
        description: "Failed to set source project",
        variant: "destructive",
      });
      return;
    }
    toast({
      title: projectId ? "Pulling bundle from project" : "Detached from project",
    });
    await fetchClient();
  };

  const openEdit = () => {
    setEditName(client.name);
    setEditDescription(client.description || "");
    setShowEdit(true);
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
        toast({
          title: "Error",
          description: "Failed to update client",
          variant: "destructive",
        });
        return;
      }
      setShowEdit(false);
      toast({ title: "Client updated" });
      await fetchClient();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const { error } = await deleteClientAction(clientId);
      if (error) {
        toast({
          title: "Error",
          description: "Failed to delete client",
          variant: "destructive",
        });
        return;
      }
      toast({ title: "Client deleted" });
      router.push("/clients");
    } finally {
      setDeleting(false);
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
          <div className="flex items-center gap-1.5">
            <Button size="xs" variant="outline" onClick={openEdit}>
              <Pencil className="mr-1 h-3.5 w-3.5" />
              Edit
            </Button>
            <Button
              size="xs"
              variant="ghost"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => setShowDelete(true)}
              aria-label="Delete client"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ),
      }}
    >
      <div className="mx-auto w-full max-w-5xl space-y-6">
        {/* Identity — what this client is and how to connect to it. */}
        <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
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
                {sourceProject && (
                  <Badge variant="secondary" className="gap-1 text-xs">
                    <EntityIcon kind="project" className="h-3 w-3" />
                    {sourceProject.name}
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                {client.description ||
                  "A governed, scoped tool bundle an external harness can connect to over MCP."}
              </p>
            </div>
          </div>

          {/* Connect endpoint + CLI — how a harness attaches to this client. */}
          <div className="space-y-2 border-t border-border/50 pt-3">
            {client.mcp_endpoint_url && (
              <div className="flex items-center gap-2">
                <div className="flex w-28 shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <LinkIcon className="h-3.5 w-3.5" />
                  <span>MCP endpoint</span>
                </div>
                <code className="min-w-0 flex-1 break-all rounded bg-muted/40 px-2 py-1 font-mono text-xs">
                  {client.mcp_endpoint_url}
                </code>
                <CopyButton text={client.mcp_endpoint_url} label="endpoint" />
              </div>
            )}
            <div className="flex items-center gap-2">
              <div className="flex w-28 shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                <Terminal className="h-3.5 w-3.5" />
                <span>Sync command</span>
              </div>
              <code className="min-w-0 flex-1 break-all rounded bg-muted/40 px-2 py-1 font-mono text-xs">
                {syncCmd}
              </code>
              <CopyButton text={syncCmd} label="command" />
            </div>
          </div>
        </div>

        {/* Source project — inherit a project's bundle on top of this client. */}
        <div className="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
          <label
            htmlFor="client-source-project"
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
          >
            <EntityIcon kind="project" className="h-3.5 w-3.5" />
            Pull bundle from project
          </label>
          <select
            id="client-source-project"
            className="w-full max-w-md rounded-md border bg-background text-foreground [color-scheme:light] dark:[color-scheme:dark] px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            value={client.source_project_id || ""}
            onChange={(e) => handlePull(e.target.value)}
          >
            <option value="">None (standalone)</option>
            {allProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <p className="note">
            {client.source_project_id
              ? "Effective bundle = this client's own attachments plus the source project's."
              : "Attach a project to inherit its skills and tools on top of this client's own."}
          </p>
        </div>

        {/* Scope — the MCP instances and skills exposed through the endpoint. */}
        <div className="grid gap-4 md:grid-cols-2">
          <ScopeSection
            title="MCP Instances"
            kind="mcp"
            emptyLabel="No MCP instances connected yet."
            items={client.mcp_instances || []}
            allItems={allMcp}
            onAdd={handleAddMcp}
            onRemove={handleRemoveMcp}
            addLabel="Add"
            placeholder="Select an MCP instance…"
          />
          <ScopeSection
            title="Skills"
            kind="skill"
            emptyLabel="No skills connected yet."
            items={client.skills || []}
            allItems={allSkills}
            onAdd={handleAddSkill}
            onRemove={handleRemoveSkill}
            addLabel="Add"
            placeholder="Select a skill…"
          />
        </div>
      </div>

      <Dialog open={showEdit} onOpenChange={setShowEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Client</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <input
              aria-label="Client name"
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              placeholder="Name, e.g. my-codex"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
            <textarea
              aria-label="Client description"
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              placeholder="Description (optional)"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEdit(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!editName.trim() || saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showDelete} onOpenChange={setShowDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Client</DialogTitle>
          </DialogHeader>
          <p className="py-2 text-sm text-muted-foreground">
            Delete{" "}
            <span className="font-medium text-foreground">{client.name}</span>?
            The scoped MCP endpoint will stop working for any harness connected
            to it. This cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
