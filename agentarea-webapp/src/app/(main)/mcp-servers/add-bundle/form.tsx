"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  createMCPServerInstanceAction,
  listMCPServerInstancesAction,
} from "@/lib/server-actions";

interface MCPInstance {
  id: string;
  name: string;
  description?: string | null;
}

export function CreateBundleForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [instances, setInstances] = useState<MCPInstance[]>([]);
  const [loadingInstances, setLoadingInstances] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listMCPServerInstancesAction()
      .then((result) => {
        const data = result.data as MCPInstance[] | null;
        setInstances(data || []);
      })
      .catch(() => setInstances([]))
      .finally(() => setLoadingInstances(false));
  }, []);

  const toggleMember = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || selectedIds.length === 0) return;

    setSaving(true);
    setError(null);

    try {
      const result = await createMCPServerInstanceAction({
        name: name.trim(),
        description: description.trim() || null,
        json_spec: { type: "bundle", members: selectedIds },
      });

      if (result.error) {
        setError(
          typeof result.error === "string"
            ? result.error
            : "Failed to create bundle"
        );
        return;
      }

      const newInstance = result.data as { id: string };
      router.push(`/mcp-servers/${newInstance.id}`);
    } catch {
      setError("An unexpected error occurred");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-xl space-y-6">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          placeholder="My Bundle"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          placeholder="Optional description..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </div>

      <div className="space-y-2">
        <Label>Member Servers</Label>
        {loadingInstances ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading servers...
          </div>
        ) : instances.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No MCP server instances found. Create some instances first.
          </p>
        ) : (
          <div className="space-y-2 rounded-lg border border-border p-3">
            {instances.map((instance) => (
              <div key={instance.id} className="flex items-start gap-3">
                <Checkbox
                  id={`member-${instance.id}`}
                  checked={selectedIds.includes(instance.id)}
                  onCheckedChange={() => toggleMember(instance.id)}
                />
                <label
                  htmlFor={`member-${instance.id}`}
                  className="flex cursor-pointer flex-col gap-0.5"
                >
                  <span className="text-sm font-medium">{instance.name}</span>
                  {instance.description && (
                    <span className="text-xs text-muted-foreground">
                      {instance.description}
                    </span>
                  )}
                </label>
              </div>
            ))}
          </div>
        )}
        {selectedIds.length === 0 && !loadingInstances && instances.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Select at least one server to include in the bundle.
          </p>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex gap-3">
        <Button
          type="submit"
          disabled={!name.trim() || selectedIds.length === 0 || saving}
        >
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Create Bundle
        </Button>
        <Button type="button" variant="outline" onClick={() => router.back()}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
