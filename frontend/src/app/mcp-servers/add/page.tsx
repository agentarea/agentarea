import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AddMCPServerForm } from "./add-mcp-server-form";

export default function AddMCPServerPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle>Add MCP Server</CardTitle>
          <CardDescription>
            Connect a Docker-based MCP server to your workspace
          </CardDescription>
        </CardHeader>
        <AddMCPServerForm />
      </Card>
    </div>
  );
} 