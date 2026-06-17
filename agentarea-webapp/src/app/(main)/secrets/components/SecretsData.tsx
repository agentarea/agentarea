import EmptyState from "@/components/EmptyState";
import { listMCPServerInstances } from "@/lib/api";
import { SecretsTable } from "./SecretsTable";

type MCPInstance = {
  id: string;
  name: string;
  auth_type?: string | null;
  status?: string | null;
  created_at?: string | null;
};

export async function SecretsData() {
  let instances: MCPInstance[] = [];
  let error: string | null = null;

  try {
    const { data, error: apiError } = await listMCPServerInstances();
    if (apiError) {
      console.error("Failed to fetch MCP server instances:", apiError);
      error = "Failed to load connections";
    } else {
      instances = ((data as any) ?? []) as MCPInstance[];
    }
  } catch (e) {
    console.error("Failed to load secrets data:", e);
    error = e instanceof Error ? e.message : "Failed to load connections";
  }

  return (
    <div className="space-y-6">
      {error ? (
        <EmptyState
          title="Couldn't load connections"
          description={error}
          iconsType="mcp"
          action={{ label: "View MCP connections", href: "/mcp-servers" }}
        />
      ) : instances.length === 0 ? (
        <EmptyState
          title="No MCP connections"
          description="Add an MCP server connection to manage its credentials here."
          iconsType="mcp"
          action={{ label: "Add connection", href: "/mcp-servers" }}
        />
      ) : (
        <SecretsTable instances={instances} />
      )}

    </div>
  );
}
