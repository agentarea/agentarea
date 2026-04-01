"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Layers, Trash2, Plus, GripVertical, Copy, Check } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getCompoundMCPAction,
  updateCompoundMCPAction,
  deleteCompoundMCPAction,
  listCompoundMCPMembersAction,
  addCompoundMCPMemberAction,
  removeCompoundMCPMemberAction,
  listMCPServerInstancesAction,
} from "@/lib/server-actions";
import { CompoundMCP, CompoundMCPMember, MCPInstance } from "../../types";

export default function CompoundMCPDetailPage() {
  const params = useParams();
  const router = useRouter();
  const compoundId = params.id as string;

  const [compound, setCompound] = useState<CompoundMCP | null>(null);
  const [members, setMembers] = useState<CompoundMCPMember[]>([]);
  const [allInstances, setAllInstances] = useState<MCPInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Edit state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editRoutingMode, setEditRoutingMode] = useState("");
  const [saving, setSaving] = useState(false);

  // Add member state
  const [addingMember, setAddingMember] = useState(false);
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [memberOrder, setMemberOrder] = useState(0);

  const loadData = useCallback(async () => {
    try {
      const [compoundRes, membersRes, instancesRes] = await Promise.all([
        getCompoundMCPAction(compoundId),
        listCompoundMCPMembersAction(compoundId),
        listMCPServerInstancesAction(),
      ]);

      if (compoundRes.error) {
        setError((compoundRes.error as any)?.detail || "Failed to load compound MCP");
      } else {
        const c = compoundRes.data as any as CompoundMCP;
        setCompound(c);
        setEditName(c.name);
        setEditDescription(c.description || "");
        setEditRoutingMode(c.routing_mode);
      }

      if (!membersRes.error) {
        setMembers((membersRes.data || []) as CompoundMCPMember[]);
      }

      if (!instancesRes.error) {
        setAllInstances((instancesRes.data || []) as MCPInstance[]);
      }
    } catch {
      setError("Failed to load compound MCP");
    } finally {
      setLoading(false);
    }
  }, [compoundId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await updateCompoundMCPAction(compoundId, {
        name: editName.trim() || undefined,
        description: editDescription.trim() || undefined,
        routing_mode: editRoutingMode || undefined,
      });
      if (result.error) {
        setError((result.error as any)?.detail || "Failed to update");
      } else {
        setCompound(result.data as any as CompoundMCP);
        setEditing(false);
      }
    } catch {
      setError("Failed to update");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Delete this compound MCP and all its member associations?")) return;
    setDeleting(true);
    try {
      await deleteCompoundMCPAction(compoundId);
      router.push("/mcp-servers");
      router.refresh();
    } catch {
      setError("Failed to delete");
      setDeleting(false);
    }
  };

  const handleAddMember = async () => {
    if (!selectedInstanceId) return;
    setError(null);
    try {
      const result = await addCompoundMCPMemberAction(compoundId, {
        mcp_instance_id: selectedInstanceId,
        order: memberOrder,
        config: {},
      });
      if (result.error) {
        setError((result.error as any)?.detail || "Failed to add member");
      } else {
        setMembers((prev) => [...prev, result.data as any as CompoundMCPMember]);
        setSelectedInstanceId("");
        setMemberOrder(members.length);
        setAddingMember(false);
      }
    } catch {
      setError("Failed to add member");
    }
  };

  const handleRemoveMember = async (instanceId: string) => {
    setError(null);
    try {
      await removeCompoundMCPMemberAction(compoundId, instanceId);
      setMembers((prev) => prev.filter((m) => m.mcp_instance_id !== instanceId));
    } catch {
      setError("Failed to remove member");
    }
  };

  const getInstanceName = (instanceId: string) => {
    return allInstances.find((i) => i.id === instanceId)?.name || instanceId;
  };

  // Instances not already members
  const availableInstances = allInstances.filter(
    (inst) => !members.some((m) => m.mcp_instance_id === inst.id)
  );

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !compound) {
    return <div className="p-8 text-center text-destructive">{error}</div>;
  }

  if (!compound) {
    return <div className="p-8 text-center text-muted-foreground">Compound MCP not found</div>;
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Connections", href: "/mcp-servers" },
          { label: compound.name },
        ],
        description: compound.description || "Compound MCP connection",
        backLink: { label: "Back to Connections", href: "/mcp-servers" },
        controls: (
          <div className="flex gap-2">
            {!editing && (
              <Button size="xs" variant="outline" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            <Button size="xs" variant="destructive" onClick={handleDelete} disabled={deleting}>
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </div>
        ),
      }}
    >
      <div className="space-y-6">
        {error && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Info / Edit */}
        <div className="rounded-lg border p-4">
          {editing ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="edit-name">Name</Label>
                <Input
                  id="edit-name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-desc">Description</Label>
                <Textarea
                  id="edit-desc"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-routing">Routing Mode</Label>
                <Select value={editRoutingMode} onValueChange={setEditRoutingMode}>
                  <SelectTrigger id="edit-routing">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="parallel">Parallel</SelectItem>
                    <SelectItem value="fallback">Fallback</SelectItem>
                    <SelectItem value="conditional">Conditional</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Endpoint URL */}
              <div>
                <p className="text-xs text-muted-foreground">MCP Endpoint</p>
                <div className="mt-1 flex items-center gap-2">
                  <code className="rounded bg-muted px-2 py-1 font-mono text-sm">
                    {(compound as any).endpoint_url || `/mcp/compound-${compound.name.toLowerCase().replace(/ /g, "-").replace(/_/g, "-")}`}
                  </code>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Connect to this URL from any MCP client. Start the proxy after adding members.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Type</p>
                  <div className="mt-1 flex items-center gap-1.5">
                    <Layers className="h-4 w-4 text-violet-500" />
                    <Badge variant="outline" className="text-violet-600 border-violet-300">Compound</Badge>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Routing Mode</p>
                  <div className="mt-1">
                    <Badge variant="outline" className="capitalize">
                      {compound.routing_mode}
                    </Badge>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {compound.routing_mode === "parallel" && "Merges tools from all members into one toolset"}
                      {compound.routing_mode === "fallback" && "Tries members in priority order; uses first that responds"}
                      {compound.routing_mode === "conditional" && "Routes tool calls to specific members based on rules"}
                    </p>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Members</p>
                  <p className="mt-1 text-sm">{members.length} MCP instance{members.length !== 1 ? "s" : ""}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Created</p>
                  <p className="mt-1 text-sm">{new Date(compound.created_at).toLocaleDateString()}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Members */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-medium">
              Members ({members.length})
            </h3>
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                setAddingMember(true);
                setMemberOrder(members.length);
              }}
              disabled={availableInstances.length === 0}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add Member
            </Button>
          </div>

          {/* Add member form */}
          {addingMember && (
            <div className="mb-4 rounded-lg border border-dashed p-4 space-y-3">
              <div className="space-y-2">
                <Label>MCP Instance</Label>
                <Select value={selectedInstanceId} onValueChange={setSelectedInstanceId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select an MCP instance..." />
                  </SelectTrigger>
                  <SelectContent>
                    {availableInstances.map((inst) => (
                      <SelectItem key={inst.id} value={inst.id}>
                        {inst.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Order</Label>
                <Input
                  type="number"
                  min={0}
                  value={memberOrder}
                  onChange={(e) => setMemberOrder(parseInt(e.target.value) || 0)}
                />
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={handleAddMember} disabled={!selectedInstanceId}>
                  Add
                </Button>
                <Button size="sm" variant="outline" onClick={() => setAddingMember(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {members.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No members yet. Add MCP instances to this compound.
            </p>
          ) : (
            <div className="grid gap-2">
              {members
                .sort((a, b) => a.order - b.order)
                .map((member) => (
                  <div
                    key={member.mcp_instance_id}
                    className="flex items-center justify-between rounded-md border px-3 py-2"
                  >
                    <div className="flex items-center gap-3">
                      <GripVertical className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">
                          {getInstanceName(member.mcp_instance_id)}
                        </p>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-muted-foreground">
                            ns:{member.namespace}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            order:{member.order}
                          </span>
                        </div>
                      </div>
                    </div>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => handleRemoveMember(member.mcp_instance_id)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                    </Button>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </ContentBlock>
  );
}
