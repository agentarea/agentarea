import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listMCPServers } from "@/lib/api";
import { Download, Edit, Globe, Link as LinkIcon, Server, Trash2 } from "lucide-react";
import Link from "next/link";

export default async function MCPServersPage() {
  const mcpServers = await listMCPServers();

  const mcpList = mcpServers.data;

  return (
    <div className="p-6">
      <div className="flex flex-col space-y-4 mb-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-semibold">My MCP Servers</h1>
          <div className="flex space-x-2">
            <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
              <Link href="/mcp-servers/add?type=self-hosted" className="flex items-center gap-1">
                <Server className="h-4 w-4" />
                Add Self-Hosted Server
              </Link>
            </Button>
            <Button asChild variant="outline" className="border-blue-600 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950 transition-all duration-200">
              <Link href="/mcp-servers/add?type=external" className="flex items-center gap-1">
                <Globe className="h-4 w-4" />
                Add External Server
              </Link>
            </Button>
          </div>
        </div>
        
        {mcpList && mcpList.length > 0 && (
          <div className="flex items-center space-x-2">
            <Button variant="outline" size="sm" className="text-xs">
              All Servers
            </Button>
            <Button variant="ghost" size="sm" className="text-xs">
              Self-Hosted
            </Button>
            <Button variant="ghost" size="sm" className="text-xs">
              External
            </Button>
          </div>
        )}
      </div>

      {mcpList && mcpList.length > 0 ? (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Hosting Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Downloads</TableHead>
                <TableHead>Visibility</TableHead>
                <TableHead>Last Updated</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mcpList.map((server) => {
                // Determine if server is self-hosted or external based on properties
                // This is a placeholder logic - adjust based on your actual data structure
                const isExternalServer = server.docker_image_url?.includes('http') || false;
                const hostingType = isExternalServer ? 'external' : 'self-hosted';
                
                return (
                  <TableRow key={server.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Server className="h-4 w-4 text-primary" />
                        {server.name}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1 max-w-md truncate">
                        {server.description}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge 
                        variant="outline"
                        className={hostingType === 'self-hosted' 
                          ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300' 
                          : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950 dark:text-purple-300'
                        }
                      >
                        <div className="flex items-center gap-1">
                          {hostingType === 'self-hosted' 
                            ? <Server className="h-3 w-3 mr-1" /> 
                            : <Globe className="h-3 w-3 mr-1" />
                          }
                          {hostingType === 'self-hosted' ? 'Self-Hosted' : 'External'}
                        </div>
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge 
                        variant={server.status === 'published' ? 'default' : 'secondary'}
                        className={server.status === 'published' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : server.status === 'draft' ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'}
                      >
                        {server.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Download className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </TableCell>
                    <TableCell>{server.is_public ? "Public" : "Private"}</TableCell>
                    <TableCell>{new Date(server.updated_at).toLocaleDateString()}</TableCell> 
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {hostingType === 'self-hosted' ? (
                          // Actions for self-hosted servers
                          <>
                            <Button variant="outline" size="sm" className="h-8 px-2 text-xs">
                              <Server className="h-3 w-3 mr-1" />
                              Deploy
                            </Button>
                            <Button variant="outline" size="sm" className="h-8 w-8 p-0" asChild>
                              <Link href={`/mcp-servers/edit/${server.id}`}>
                                <Edit className="h-4 w-4" />
                                <span className="sr-only">Edit</span>
                              </Link>
                            </Button>
                          </>
                        ) : (
                          // Actions for external servers
                          <>
                            <Button variant="outline" size="sm" className="h-8 px-2 text-xs">
                              <LinkIcon className="h-3 w-3 mr-1" />
                              Test
                            </Button>
                            <Button variant="outline" size="sm" className="h-8 w-8 p-0" asChild>
                              <Link href={`/mcp-servers/edit/${server.id}`}>
                                <Edit className="h-4 w-4" />
                                <span className="sr-only">Edit</span>
                              </Link>
                            </Button>
                          </>
                        )}
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="h-8 w-8 p-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                          // onClick={() => handleDeleteServer(server.id)} // Requires client component
                        >
                          <Trash2 className="h-4 w-4" />
                          <span className="sr-only">Remove (requires client interaction)</span>
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
        <Card className="p-8 text-center">
          <p className="text-muted-foreground mb-4">
            You haven&apos;t added any MCP servers yet.
          </p>
          <div className="flex justify-center space-x-4">
            <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
              <Link href="/mcp-servers/add?type=self-hosted" className="flex items-center gap-1">
                <Server className="h-4 w-4" />
                Add Self-Hosted Server
              </Link>
            </Button>
            <Button asChild variant="outline" className="border-blue-600 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950">
              <Link href="/mcp-servers/add?type=external" className="flex items-center gap-1">
                <Globe className="h-4 w-4" />
                Add External Server
              </Link>
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
} 