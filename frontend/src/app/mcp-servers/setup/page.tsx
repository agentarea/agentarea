import { listMCPServerInstances, listMCPServers } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { components } from '@/api/schema';

import MCPInstanceForm from './MCPInstanceForm';

type MCPServer = components["schemas"]["MCPServerResponse"];
type MCPServerInstance = components["schemas"]["MCPServerInstanceResponse"];

export default async function MCPSetupPage() {
  // Fetch all MCP servers and instances
  const [serversRes, instancesRes] = await Promise.all([
    listMCPServers(),
    listMCPServerInstances()
  ]);
  const servers: MCPServer[] = serversRes.data || [];
  const instances: MCPServerInstance[] = instancesRes.data || [];

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Setup MCP Server Instance</CardTitle>
        </CardHeader>
        <CardContent>
          <MCPInstanceForm servers={servers} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Existing MCP Server Instances</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {instances.length === 0 && <li className="text-muted-foreground">No instances found.</li>}
            {instances.map((inst) => (
              <li key={inst.id} className="border rounded p-3">
                <div className="font-semibold">{inst.name}</div>
                <div className="text-xs text-muted-foreground">Server: {inst.server_id}</div>
                <div className="text-xs">Endpoint: {inst.endpoint_url}</div>
                <div className="text-xs">Status: {inst.status}</div>
                <div className="text-xs">Config: <pre className="whitespace-pre-wrap break-all">{JSON.stringify(inst.config, null, 2)}</pre></div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
} 