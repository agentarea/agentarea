"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Search, Grid, List } from "lucide-react";
import { CreateInstanceDialog } from "./CreateInstanceDialog";

interface MCPServer {
  id: string;
  name: string;
  description: string;
  docker_image_url: string;
  version: string;
  tags: string[];
  status: string;
  is_public: boolean;
  env_schema?: Array<{
    [key: string]: unknown;
  }>;
  cmd?: string[] | null;
  created_at: string;
  updated_at: string;
}

interface MCPSpecsSectionProps {
  mcpServers: MCPServer[];
  searchParams: { [key: string]: string | string[] | undefined };
}

// Helper function to get category icon based on tags
const getCategoryIcon = (tags: string[]) => {
  if (tags.some(tag => tag.includes('ai') || tag.includes('llm') || tag.includes('search') || tag.includes('memory'))) return '🤖';
  if (tags.some(tag => tag.includes('database') || tag.includes('data') || tag.includes('analytics'))) return '📊';
  if (tags.some(tag => tag.includes('git') || tag.includes('repository') || tag.includes('github'))) return '🐙';
  if (tags.some(tag => tag.includes('web') || tag.includes('browser') || tag.includes('fetch'))) return '🌐';
  if (tags.some(tag => tag.includes('file') || tag.includes('filesystem'))) return '📁';
  if (tags.some(tag => tag.includes('message') || tag.includes('slack') || tag.includes('gmail'))) return '💬';
  return '🔧';
};

// Helper function to get category from tags
const getCategory = (tags: string[]) => {
  if (tags.some(tag => tag.includes('ai') || tag.includes('llm') || tag.includes('search') || tag.includes('memory'))) return 'AI';
  if (tags.some(tag => tag.includes('database') || tag.includes('data') || tag.includes('analytics'))) return 'Data';
  if (tags.some(tag => tag.includes('git') || tag.includes('repository') || tag.includes('github'))) return 'Dev';
  if (tags.some(tag => tag.includes('web') || tag.includes('browser') || tag.includes('fetch'))) return 'Web';
  if (tags.some(tag => tag.includes('file') || tag.includes('filesystem'))) return 'Files';
  if (tags.some(tag => tag.includes('message') || tag.includes('slack') || tag.includes('gmail'))) return 'Messaging';
  return 'Tools';
};

export function MCPSpecsSection({ mcpServers, searchParams }: MCPSpecsSectionProps) {
  const [searchQuery, setSearchQuery] = useState(searchParams.search as string || '');
  const [selectedCategory, setSelectedCategory] = useState(searchParams.category as string || 'All');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('list');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);

  // Get unique categories from servers
  const categories = useMemo(() => {
    const cats = new Set<string>();
    mcpServers.forEach(server => {
      cats.add(getCategory(server.tags || []));
    });
    return ['All', ...Array.from(cats).sort()];
  }, [mcpServers]);

  // Filter servers based on search and category
  const filteredServers = useMemo(() => {
    return mcpServers.filter(server => {
      const matchesSearch = server.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           server.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory = selectedCategory === 'All' || getCategory(server.tags || []) === selectedCategory;
      const isPublic = server.is_public; // Only show public servers
      return matchesSearch && matchesCategory && isPublic;
    });
  }, [mcpServers, searchQuery, selectedCategory]);

  // Handle opening the configuration dialog
  const handleConfigureInstance = (server: MCPServer) => {
    setSelectedServer(server);
    setDialogOpen(true);
  };

  const renderServerCard = (server: MCPServer) => {
    return (
      <div key={server.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-secondary/50 transition-colors">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            {getCategoryIcon(server.tags || [])}
          </div>
          <div>
            <h3 className="font-medium">{server.name}</h3>
            <p className="text-sm text-muted-foreground">{server.description}</p>
            <div className="flex flex-wrap gap-1 mt-1">
              {(server.tags || []).slice(0, 3).map((tag) => (
                <Badge key={tag} variant="outline" className="text-xs">
                  {tag}
                </Badge>
              ))}
              {(server.tags || []).length > 3 && (
                <Badge variant="outline" className="text-xs">
                  +{(server.tags || []).length - 3} more
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">{getCategory(server.tags || [])}</Badge>
          <Badge variant={server.status === 'active' ? 'default' : 'secondary'} className="text-xs">
            {server.status}
          </Badge>
          <Button 
            size="sm" 
            onClick={() => handleConfigureInstance(server)}
          >
            Configure
          </Button>
        </div>
      </div>
    );
  };

  const renderServerGrid = (server: MCPServer) => {
    return (
      <Card key={server.id} className="hover:shadow-md transition-shadow">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                {getCategoryIcon(server.tags || [])}
              </div>
              <div>
                <h3 className="font-medium">{server.name}</h3>
                <Badge variant="secondary" className="text-xs mt-1">
                  {getCategory(server.tags || [])}
                </Badge>
              </div>
            </div>
            <Badge variant={server.status === 'active' ? 'default' : 'secondary'} className="text-xs">
              {server.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground mb-3">{server.description}</p>
          <div className="flex flex-wrap gap-1 mb-3">
            {(server.tags || []).slice(0, 2).map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs">
                {tag}
              </Badge>
            ))}
            {(server.tags || []).length > 2 && (
              <Badge variant="outline" className="text-xs">
                +{(server.tags || []).length - 2}
              </Badge>
            )}
          </div>
          <Button 
            size="sm" 
            className="w-full"
            onClick={() => handleConfigureInstance(server)}
          >
            Configure
          </Button>
        </CardContent>
      </Card>
    );
  };

  return (
    <>
      <h2 className="text-xl font-semibold mb-4">🛒 Browse MCP Specifications</h2>
      
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input 
                placeholder="Search MCP specifications..." 
                className="pl-10" 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button 
                variant={viewMode === 'grid' ? 'default' : 'outline'} 
                size="sm"
                onClick={() => setViewMode('grid')}
              >
                <Grid className="h-4 w-4" />
              </Button>
              <Button 
                variant={viewMode === 'list' ? 'default' : 'outline'} 
                size="sm"
                onClick={() => setViewMode('list')}
              >
                <List className="h-4 w-4" />
              </Button>
            </div>
          </div>
          
          <div className="flex flex-wrap gap-2 mt-4">
            {categories.map((category) => (
              <Badge 
                key={category}
                variant={selectedCategory === category ? 'default' : 'outline'}
                className="cursor-pointer"
                onClick={() => setSelectedCategory(category)}
              >
                {category}
              </Badge>
            ))}
          </div>
        </CardHeader>
        
        <CardContent>
          {filteredServers.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No MCP servers found matching your criteria.</p>
              <p className="text-sm mt-2">Try adjusting your search or category filter.</p>
              {mcpServers.length === 0 && (
                <p className="text-sm mt-2 text-amber-600">No MCP servers available yet.</p>
              )}
            </div>
          ) : (
            <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-3"}>
              {filteredServers.map(server => 
                viewMode === 'grid' ? renderServerGrid(server) : renderServerCard(server)
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <CreateInstanceDialog 
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mcpServer={selectedServer}
      />
    </>
  );
} 