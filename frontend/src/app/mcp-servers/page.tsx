import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Download, Edit, Plus, Server, Trash2 } from "lucide-react";
import Link from "next/link";
import { deleteMCPServer, listMCPServers, updateMCPServer } from "@/lib/api";

// Define a basic type for MCPServer if not available from API import
interface MCPServer {
  id: string;
  name: string;
  description: string;
  status: 'published' | 'draft' | 'pending' | 'rejected'; // Example statuses
  downloads: number;
  isPublic: boolean;
  lastUpdated: string; // Or Date
  // Add other fields as necessary based on listMCPServers response
  tags?: string[];
  author?: string;
  stars?: number;
  verified?: boolean;
}

export default async function MCPServersPage() {
  const mcpServers = await listMCPServers();

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">My MCP Servers</h1>
        <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
          <Link href="/mcp-servers/add" className="flex items-center gap-1">
            <Plus className="h-4 w-4" />
            Add MCP Server
          </Link>
        </Button>
      </div>

      {mcpServers && mcpServers.length > 0 ? (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Downloads</TableHead>
                <TableHead>Visibility</TableHead>
                <TableHead>Last Updated</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mcpServers.map((server: MCPServer) => (
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
                      variant={server.status === 'published' ? 'default' : 'secondary'}
                      className={server.status === 'published' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : server.status === 'draft' ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'}
                    >
                      {server.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Download className="h-4 w-4 text-muted-foreground" />
                      {server.downloads}
                    </div>
                  </TableCell>
                  <TableCell>{server.isPublic ? "Public" : "Private"}</TableCell>
                  <TableCell>{new Date(server.lastUpdated).toLocaleDateString()}</TableCell> 
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      {/* Add Analytics button if needed */}
                      <Button variant="outline" size="sm" className="h-8 w-8 p-0" asChild>
                        <Link href={`/mcp-servers/edit/${server.id}`}>
                          <Edit className="h-4 w-4" />
                          <span className="sr-only">Edit</span>
                        </Link>
                      </Button>
                      {/* Add Remove button functionality later if needed */}
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
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <Card className="p-8 text-center">
          <p className="text-muted-foreground mb-4">
            You haven't added any MCP servers yet.
          </p>
          <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
            <Link href="/mcp-servers/add" className="flex items-center gap-1">
              <Plus className="h-4 w-4" />
              Add Your First Server
            </Link>
          </Button>
        </Card>
      )}
    </div>
  );
} 