"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
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
import { createCompoundMCPAction } from "@/lib/server-actions";

const ROUTING_MODES = [
  { value: "parallel", label: "Parallel", description: "Merge tools from all members into a single unified toolset" },
  { value: "fallback", label: "Fallback", description: "Try members in priority order; use first that responds" },
  { value: "conditional", label: "Conditional", description: "Route tool calls to specific members based on rules" },
] as const;

export function AddCompoundForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [routingMode, setRoutingMode] = useState<string>("parallel");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setSaving(true);
    setError(null);

    try {
      const result = await createCompoundMCPAction({
        name: name.trim(),
        description: description.trim() || undefined,
        routing_mode: routingMode,
      });

      if (result.error) {
        setError(typeof result.error === "string" ? result.error : "Failed to create compound MCP");
        return;
      }

      const compound = result.data as any;
      router.push(`/mcp-servers/compound/${compound.id}`);
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
          placeholder="My Compound MCP"
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
        <Label htmlFor="routing-mode">Routing Mode</Label>
        <Select value={routingMode} onValueChange={setRoutingMode}>
          <SelectTrigger id="routing-mode">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROUTING_MODES.map((mode) => (
              <SelectItem key={mode.value} value={mode.value}>
                <div className="flex flex-col">
                  <span>{mode.label}</span>
                  <span className="text-xs text-muted-foreground">{mode.description}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={!name.trim() || saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Create Compound MCP
        </Button>
        <Button type="button" variant="outline" onClick={() => router.back()}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
