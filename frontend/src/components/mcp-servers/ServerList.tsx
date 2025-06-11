import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState/EmptyState";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Settings, Globe, Server, BookOpen } from "lucide-react";
import Link from "next/link";

type MCPServer = {
  id: string;
  name: string;
  description: string;
  status: string;
  is_public: boolean;
  updated_at: string;
  docker_image_url?: string;
};

interface ServerListProps {
  mcpList: MCPServer[];
}

export function ServerList({ mcpList }: ServerListProps) {
  return (
    <>
      <div className="flex items-center space-x-2 mb-4">
        <BookOpen className="h-5 w-5 text-primary" />
        <h2 className="text-xl font-semibold">Available MCP Providers</h2>
        <Badge variant="secondary" className="ml-2">
          {mcpList?.length || 0} providers
        </Badge>
      </div>

      {mcpList && mcpList.length > 0 && (
        <div className="flex items-center space-x-2 mb-4">
          <Button variant="outline" size="sm" className="text-xs">
            All Providers
          </Button>
          <Button variant="ghost" size="sm" className="text-xs">
            Self-Hosted
          </Button>
          <Button variant="ghost" size="sm" className="text-xs">
            External
          </Button>
        </div>
      )}

      {mcpList && mcpList.length > 0 ? (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Capabilities</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mcpList.map((server) => {
                // Determine if server is self-hosted or external based on properties
                const isExternalServer = server.docker_image_url?.includes('http') || false;
                const providerType = isExternalServer ? 'external' : 'self-hosted';
                
                // Categorize providers by name/description
                const getCategory = (name: string, description: string) => {
                  const nameDesc = `${name} ${description}`.toLowerCase();
                  if (nameDesc.includes('database') || nameDesc.includes('sql') || nameDesc.includes('mongo') || nameDesc.includes('redis') || nameDesc.includes('elasticsearch')) return 'Database';
                  if (nameDesc.includes('git') || nameDesc.includes('github') || nameDesc.includes('docker') || nameDesc.includes('kubernetes')) return 'Development';
                  if (nameDesc.includes('slack') || nameDesc.includes('gmail') || nameDesc.includes('email')) return 'Communication';
                  if (nameDesc.includes('file') || nameDesc.includes('memory') || nameDesc.includes('fetch') || nameDesc.includes('web')) return 'System';
                  if (nameDesc.includes('puppet') || nameDesc.includes('browser')) return 'Automation';
                  if (nameDesc.includes('monitor') || nameDesc.includes('prometheus') || nameDesc.includes('jira')) return 'Monitoring';
                  return 'Tools';
                };

                const category = getCategory(server.name, server.description);
                
                return (
                  <TableRow key={server.id} className="hover:bg-muted/50">
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Server className="h-4 w-4 text-primary" />
                        <div>
                          <div className="font-medium">{server.name}</div>
                          <div className="text-xs text-muted-foreground mt-1 max-w-md">
                            {server.description}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge 
                        variant="outline"
                        className={providerType === 'self-hosted' 
                          ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300' 
                          : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950 dark:text-purple-300'
                        }
                      >
                        <div className="flex items-center gap-1">
                          {providerType === 'self-hosted' 
                            ? <Server className="h-3 w-3 mr-1" /> 
                            : <Globe className="h-3 w-3 mr-1" />
                          }
                          {providerType === 'self-hosted' ? 'Docker' : 'HTTP'}
                        </div>
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">
                        {category}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {/* Show capabilities based on category */}
                        {category === 'Database' && <Badge variant="outline" className="text-xs">Query</Badge>}
                        {category === 'Development' && <Badge variant="outline" className="text-xs">Code</Badge>}
                        {category === 'System' && <Badge variant="outline" className="text-xs">Files</Badge>}
                        {category === 'Automation' && <Badge variant="outline" className="text-xs">Browser</Badge>}
                        <Badge variant="outline" className="text-xs">API</Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button 
                          variant="default" 
                          size="sm" 
                          className="h-8 px-3 text-xs bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700"
                          asChild
                        >
                          <Link 
                            href={`/mcp-servers/setup?provider=${server.id}&type=${providerType}`}
                            className="flex items-center gap-1"
                          >
                            <Settings className="h-3 w-3" />
                            Configure
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <EmptyState
          title="No MCP providers available"
          description="MCP providers catalog is empty"
          iconsType="mcp"
          action={{
            label: "Refresh Catalog",
            href: "/mcp-servers"
          }}
        />
      )}
    </>
  );
} 