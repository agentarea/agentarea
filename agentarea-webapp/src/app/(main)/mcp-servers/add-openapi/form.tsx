"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createOpenAPIConnection, discoverOpenAPITools } from "@/lib/browser-api";

export function AddOpenAPIForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [specUrl, setSpecUrl] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const { data, error: createError } = await createOpenAPIConnection({
        name,
        base_url: baseUrl,
        description: description || undefined,
        spec_url: specUrl || undefined,
      });

      if (createError) {
        setError((createError as any)?.detail || "Failed to create connection");
        return;
      }

      // Auto-discover tools if spec_url was provided
      if (specUrl && data?.id) {
        try {
          await discoverOpenAPITools(data.id);
        } catch {
          // Non-fatal — tools can be discovered later
        }
      }

      router.push("/mcp-servers");
      router.refresh();
    } catch (err) {
      setError("Failed to create connection");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-xl space-y-6">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          placeholder="e.g. Stripe API"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="base_url">Base URL</Label>
        <Input
          id="base_url"
          placeholder="https://api.stripe.com"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          required
          type="url"
        />
        <p className="text-xs text-muted-foreground">
          The base URL for API requests
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="spec_url">OpenAPI Spec URL (optional)</Label>
        <Input
          id="spec_url"
          placeholder="https://api.example.com/openapi.json"
          value={specUrl}
          onChange={(e) => setSpecUrl(e.target.value)}
          type="url"
        />
        <p className="text-xs text-muted-foreground">
          URL to the OpenAPI 3.x spec (JSON or YAML). Tools will be auto-discovered.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description (optional)</Label>
        <Input
          id="description"
          placeholder="Payment processing API"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={loading || !name || !baseUrl}>
          {loading ? "Creating..." : "Create Connection"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push("/mcp-servers")}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
