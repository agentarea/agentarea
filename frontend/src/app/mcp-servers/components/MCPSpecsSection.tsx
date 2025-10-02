"use client";

import { useState, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState";
import { X } from "lucide-react";
import { CreateInstanceDialog } from "./CreateInstanceDialog";
import { MCPServerCard } from "./MCPCard";
import Table from "@/components/Table/Table";
import { useRouter } from "next/navigation";

interface MCPSpec {
  id: string;
  name: string;
  description: string;
  docker_image_url: string;
  version: string;
  tags: string[];
  status: string;
  is_public: boolean;
  env_schema?: Array<{
    name: string;
    description: string;
    required: boolean;
    default?: string;
  }>;
  cmd?: string[] | null;
  created_at: string;
  updated_at: string;
}

interface MCPSpecsSectionProps {
  mcpServers: MCPSpec[];
  searchParams: { [key: string]: string | string[] | undefined };
  isLoading?: boolean;
  viewMode?: string;
  searchQuery?: string;
  hasNoData?: boolean;
}

// Get category from tags
const getCategory = (tags: string[]) => {
  if (tags.some(tag => tag.includes('ai') || tag.includes('llm') || tag.includes('search') || tag.includes('memory'))) return 'AI';
  if (tags.some(tag => tag.includes('database') || tag.includes('data') || tag.includes('analytics'))) return 'Data';
  if (tags.some(tag => tag.includes('git') || tag.includes('repository') || tag.includes('github'))) return 'Dev';
  if (tags.some(tag => tag.includes('web') || tag.includes('browser') || tag.includes('fetch'))) return 'Web';
  if (tags.some(tag => tag.includes('file') || tag.includes('filesystem'))) return 'Files';
  if (tags.some(tag => tag.includes('message') || tag.includes('slack') || tag.includes('gmail'))) return 'Messaging';
  return 'Tools';
};

// Enhanced category colors
const getCategoryColor = (category: string) => {
  switch (category) {
    case 'AI': return 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800';
    case 'Data': return 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/30 dark:text-blue-300 dark:border-blue-800';
    case 'Dev': return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-300 dark:border-orange-800';
    case 'Web': return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-300 dark:border-green-800';
    case 'Files': return 'bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/30 dark:text-yellow-300 dark:border-yellow-800';
    case 'Messaging': return 'bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-950/30 dark:text-pink-300 dark:border-pink-800';
    default: return 'bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-950/30 dark:text-gray-300 dark:border-gray-800';
  }
};

export function MCPSpecsSection({ 
  mcpServers, 
  searchParams, 
  isLoading = false, 
  viewMode = 'grid',
  searchQuery: propSearchQuery = '',
  hasNoData = false
}: MCPSpecsSectionProps) {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState(searchParams.search as string || '');
  const [selectedCategory, setSelectedCategory] = useState(searchParams.category as string || 'All');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPSpec | null>(null);

  // Get unique categories from servers
  const categories = useMemo(() => {
    const cats = new Set<string>();
    mcpServers.forEach(server => {
      if (server.is_public) {
        cats.add(getCategory(server.tags || []));
      }
    });
    return ['All', ...Array.from(cats).sort()];
  }, [mcpServers]);

  // Filter servers based on search and category
  const filteredServers = useMemo(() => {
    return mcpServers.filter(server => {
      const matchesSearch = server.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           server.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           (server.tags || []).some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()));
      const matchesCategory = selectedCategory === 'All' || getCategory(server.tags || []) === selectedCategory;
      const isPublic = server.is_public;
      return matchesSearch && matchesCategory && isPublic;
    });
  }, [mcpServers, searchQuery, selectedCategory]);

  // Handle opening the configuration dialog
  const handleConfigureInstance = (server: MCPSpec) => {
    setSelectedServer(server);
    setDialogOpen(true);
  };

  // Clear filters
  const clearFilters = () => {
    setSelectedCategory('All');
  };

  // Define table columns for servers
  const serverColumns = [
    {
      accessor: "name",
      header: "Name",
      render: (value: string) => <span className="truncate">{value}</span>,
    },
    {
      accessor: "description",
      header: "Description",
      render: (value: string) => (
        <span className="truncate text-sm text-gray-500">{value}</span>
      ),
    },
    {
      accessor: "tags",
      header: "Category",
      render: (value: string[]) => {
        const category = getCategory(value || []);
        const categoryColor = getCategoryColor(category);
        return (
          <Badge className={`text-xs border ${categoryColor}`}>
            {category}
          </Badge>
        );
      },
    },
    {
      accessor: "version",
      header: "Version",
      render: (value: string) => (
        <span className="text-xs text-gray-500">v{value}</span>
      ),
    },
  ];

  return (
    <div>
      <div>
        <div className="space-y-4">
          {/* Enhanced Category Filters */}
          {(selectedCategory !== 'All' || searchQuery) && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Categories</span>
                {(selectedCategory !== 'All') && (
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    <X className="h-4 w-4 mr-1" />
                    Clear filters
                  </Button>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {categories.map((category) => {
                  const isSelected = selectedCategory === category;
                  const categoryColor = category === 'All' ? 'bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-950/30 dark:text-slate-300 dark:border-slate-800' : getCategoryColor(category);
                  
                  return (
                    <Badge 
                      key={category}
                      className={`cursor-pointer transition-all duration-200 border-2 px-3 py-1 ${
                        isSelected 
                          ? `${categoryColor} ring-2 ring-primary/50 shadow-sm` 
                          : 'bg-background hover:bg-secondary border-border hover:border-primary/50'
                      }`}
                      onClick={() => setSelectedCategory(category)}
                    >
                      {category}
                      {category !== 'All' && (
                        <span className="ml-2 text-xs opacity-60">
                          {mcpServers.filter(s => s.is_public && getCategory(s.tags || []) === category).length}
                        </span>
                      )}
                    </Badge>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        
        <div>
          {isLoading ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Loading...
            </div>
          ) : filteredServers.length === 0 ? (
            <div className="py-1">
              <EmptyState 
                title={hasNoData ? "No MCP specifications" : "No matching specifications"}
                description={hasNoData 
                  ? "No MCP server specifications are available in the catalog yet" 
                  : `No specifications match your search query: "${propSearchQuery}"`
                }
                iconsType="mcp"
              />
            </div>
          ) : viewMode === 'table' ? (
            <Table 
              data={filteredServers} 
              columns={serverColumns}
              onRowClick={(server) => {
                handleConfigureInstance(server);
              }}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
              {filteredServers.map(server => (
                <MCPServerCard 
                  key={server.id} 
                  server={server}
                  onClick={() => handleConfigureInstance(server)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <CreateInstanceDialog 
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mcpServer={selectedServer}
      />
    </div>
  );
}
