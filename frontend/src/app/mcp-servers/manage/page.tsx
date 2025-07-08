import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { listMCPServerInstances } from "@/lib/api";
import { ArrowLeft, Settings, Trash2, CheckCircle, AlertCircle, ExternalLink } from "lucide-react";
import Link from "next/link";

export default async function ManageMCPsPage() {
  const mcpInstances = await listMCPServerInstances();
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-4 mb-4">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/mcp-servers" className="flex items-center gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to MCP Setup
            </Link>
          </Button>
        </div>
        <h1 className="text-3xl font-bold mb-2">📋 Manage My MCPs</h1>
        <p className="text-muted-foreground">Configure and manage your MCP resources</p>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total MCPs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{mcpInstanceList.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Available</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {mcpInstanceList.filter(i => i.status === 'running').length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Need Setup</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-amber-600">
              {mcpInstanceList.filter(i => i.status !== 'running').length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">This Week</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {mcpInstanceList.filter(i => {
                const weekAgo = new Date();
                weekAgo.setDate(weekAgo.getDate() - 7);
                return new Date(i.created_at) > weekAgo;
              }).length}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* MCP List */}
      <div className="space-y-4">
        {mcpInstanceList.length > 0 ? (
          mcpInstanceList.map((instance) => (
            <Card key={instance.id} className="hover:shadow-md transition-shadow">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center">
                      {instance.status === 'running' ? (
                        <CheckCircle className="h-6 w-6 text-green-600" />
                      ) : (
                        <AlertCircle className="h-6 w-6 text-amber-600" />
                      )}
                    </div>
                    <div>
                      <h3 className="font-semibold text-lg">{instance.name}</h3>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant={instance.status === 'running' ? 'default' : 'secondary'}>
                          {instance.status === 'running' ? 'Available' : 'Needs Setup'}
                        </Badge>
                        {instance.endpoint_url && (
                          <Badge variant="outline" className="text-xs">
                            {instance.endpoint_url.includes('http') ? 'External' : 'Self-hosted'}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground mt-2">
                        {instance.endpoint_url ? (
                          <span className="flex items-center gap-1">
                            <ExternalLink className="h-3 w-3" />
                            {instance.endpoint_url}
                          </span>
                        ) : (
                          'No endpoint configured'
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Created: {new Date(instance.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" asChild>
                      <Link href={`/mcp-servers/${instance.id}/edit`}>
                        <Settings className="h-4 w-4 mr-2" />
                        Configure
                      </Link>
                    </Button>
                    
                    <Button variant="outline" size="sm" className="text-destructive hover:text-destructive">
                      <Trash2 className="h-4 w-4 mr-2" />
                      Remove
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <div className="text-muted-foreground mb-4">
                <Settings className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <h3 className="text-lg font-semibold mb-2">No MCPs configured</h3>
                <p>Get started by adding your first MCP resource.</p>
              </div>
              <Button asChild>
                <Link href="/mcp-servers">Add Your First MCP</Link>
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Add More Button */}
      {mcpInstanceList.length > 0 && (
        <div className="mt-8 text-center">
          <Button asChild variant="outline" size="lg">
            <Link href="/mcp-servers">
              ➕ Add More MCPs
            </Link>
          </Button>
        </div>
      )}
    </div>
  );
} 