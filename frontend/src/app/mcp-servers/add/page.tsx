import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AddMCPServerForm } from "./add-mcp-server-form";
import { AddExternalMCPServerForm } from "./add-external-mcp-server-form";

export default function AddMCPServerPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle>Add MCP Server</CardTitle>
          <CardDescription>
            Connect an MCP server to your workspace
          </CardDescription>
        </CardHeader>
        <Tabs defaultValue="docker" className="px-6">
          <TabsList className="grid grid-cols-2 mb-6">
            <TabsTrigger value="docker">Docker-based</TabsTrigger>
            <TabsTrigger value="external">External</TabsTrigger>
          </TabsList>
          <TabsContent value="docker">
            <AddMCPServerForm />
          </TabsContent>
          <TabsContent value="external">
            <AddExternalMCPServerForm />
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
} 