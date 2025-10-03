"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Search, 
  Grid, 
  List, 
  Filter, 
  X, 
  Sparkles, 
  Star, 
  Download,
  FileText,
  Brain,
  GitBranch,
  Globe,
  Database,
  MessageSquare,
  Bot,
  Wrench,
  ArrowRight,
  Clock,
  CheckCircle
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
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
  mcpServers: MCPServer[];
  searchParams: { [key: string]: string | string[] | undefined };
  isLoading?: boolean;
}

// Enhanced category mapping with icons
const getCategoryIcon = (tags: string[]) => {
  if (tags.some(tag => tag.includes('ai') || tag.includes('llm') || tag.includes('search') || tag.includes('memory'))) return Brain;
  if (tags.some(tag => tag.includes('database') || tag.includes('data') || tag.includes('analytics'))) return Database;
  if (tags.some(tag => tag.includes('git') || tag.includes('repository') || tag.includes('github'))) return GitBranch;
  if (tags.some(tag => tag.includes('web') || tag.includes('browser') || tag.includes('fetch'))) return Globe;
  if (tags.some(tag => tag.includes('file') || tag.includes('filesystem'))) return FileText;
  if (tags.some(tag => tag.includes('message') || tag.includes('slack') || tag.includes('gmail'))) return MessageSquare;
  if (tags.some(tag => tag.includes('automation') || tag.includes('puppeteer'))) return Bot;
  return Wrench;
};

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

// Get popularity badge
const getPopularityInfo = (server: MCPServer) => {
  // This would ideally come from server data
  const randomFactor = Math.random();
  if (randomFactor > 0.8) return { label: 'Popular', variant: 'default' as const, icon: Star };
  if (randomFactor > 0.6) return { label: 'New', variant: 'secondary' as const, icon: Sparkles };
  return null;
};

export function MCPSpecsSection({ mcpServers, searchParams, isLoading = false }: MCPSpecsSectionProps) {
  const [searchQuery, setSearchQuery] = useState(searchParams.search as string || '');
  const [selectedCategory, setSelectedCategory] = useState(searchParams.category as string || 'All');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [showFilters, setShowFilters] = useState(false);

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
  const handleConfigureInstance = (server: MCPServer) => {
    setSelectedServer(server);
    setDialogOpen(true);
  };

  // Clear search
  const clearSearch = () => {
    setSearchQuery('');
    setSelectedCategory('All');
  };

  // Enhanced List Item
  const renderServerCard = (server: MCPServer) => {
    const IconComponent = getCategoryIcon(server.tags || []);
    const category = getCategory(server.tags || []);
    const categoryColor = getCategoryColor(category);
    const popularityInfo = getPopularityInfo(server);

    return (
      <div 
        key={server.id} 
        className="group p-4 border-2 border-slate-200 dark:border-slate-700 rounded-xl hover:border-primary/50 hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 bg-white dark:bg-slate-800/50"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 flex-1 min-w-0">
            {/* Enhanced Icon */}
            <div className="relative flex-shrink-0">
              <div className={`h-12 w-12 rounded-xl border-2 flex items-center justify-center ${categoryColor}`}>
                <IconComponent className="h-6 w-6" />
              </div>
              {popularityInfo && (
                <div className="absolute -top-1 -right-1 h-5 w-5 bg-primary rounded-full flex items-center justify-center">
                  <popularityInfo.icon className="h-3 w-3 text-white" />
                </div>
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-slate-900 dark:text-white truncate">
                  {server.name}
                </h3>
                {popularityInfo && (
                  <Badge variant={popularityInfo.variant} className="text-xs">
                    {popularityInfo.label}
                  </Badge>
                )}
              </div>
              
              <p className="text-sm text-muted-foreground mb-2 line-clamp-2">
                {server.description}
              </p>

              <div className="flex items-center gap-2 flex-wrap">
                <Badge className={`text-xs border ${categoryColor}`}>
                  {category}
                </Badge>
                <Badge 
                  variant={server.status === 'active' ? 'default' : 'secondary'} 
                  className="text-xs"
                >
                  <CheckCircle className="h-3 w-3 mr-1" />
                  {server.status}
                </Badge>
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
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-shrink-0 ml-4">
            <Button 
              size="sm" 
              onClick={() => handleConfigureInstance(server)}
              className="group/btn"
            >
              <Download className="h-4 w-4 mr-2 group-hover/btn:animate-bounce" />
              Configure
              <ArrowRight className="h-4 w-4 ml-1 group-hover/btn:translate-x-1 transition-transform" />
            </Button>
          </div>
        </div>
      </div>
    );
  };

  // Enhanced Grid Item
  const renderServerGrid = (server: MCPServer) => {
    const IconComponent = getCategoryIcon(server.tags || []);
    const category = getCategory(server.tags || []);
    const categoryColor = getCategoryColor(category);
    const popularityInfo = getPopularityInfo(server);

    return (
      <Card 
        key={server.id} 
        className="group hover:shadow-2xl hover:-translate-y-2 transition-all duration-300 border-2 border-slate-200 dark:border-slate-700 hover:border-primary/50 bg-white dark:bg-slate-800/50 overflow-hidden"
      >
        <CardHeader className="pb-4 relative">
          {/* Popular badge */}
          {popularityInfo && (
            <div className="absolute top-3 right-3">
              <Badge variant={popularityInfo.variant} className="text-xs">
                <popularityInfo.icon className="h-3 w-3 mr-1" />
                {popularityInfo.label}
              </Badge>
            </div>
          )}

          <div className="flex items-center gap-3 mb-3">
            <div className={`h-12 w-12 rounded-xl border-2 flex items-center justify-center group-hover:scale-110 transition-transform ${categoryColor}`}>
              <IconComponent className="h-6 w-6" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold line-clamp-1 group-hover:text-primary transition-colors">
                {server.name}
              </h3>
              <div className="flex items-center gap-2 mt-1">
                <Badge className={`text-xs border ${categoryColor}`}>
                  {category}
                </Badge>
                <Badge 
                  variant={server.status === 'active' ? 'default' : 'secondary'} 
                  className="text-xs"
                >
                  {server.status}
                </Badge>
              </div>
            </div>
          </div>
        </CardHeader>
        
        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground mb-4 line-clamp-3">
            {server.description}
          </p>
          
          {/* Tags */}
          <div className="flex flex-wrap gap-1 mb-4">
            {(server.tags || []).slice(0, 3).map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs">
                {tag}
              </Badge>
            ))}
            {(server.tags || []).length > 3 && (
              <Badge variant="outline" className="text-xs">
                +{(server.tags || []).length - 3}
              </Badge>
            )}
          </div>

          {/* Version info */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-4">
            <Clock className="h-3 w-3" />
            <span>v{server.version}</span>
            <span>•</span>
            <span>Updated {new Date(server.updated_at).toLocaleDateString()}</span>
          </div>
          
          <Button 
            size="sm" 
            className="w-full group/btn"
            onClick={() => handleConfigureInstance(server)}
          >
            <Download className="h-4 w-4 mr-2 group-hover/btn:animate-bounce" />
            Configure Server
            <ArrowRight className="h-4 w-4 ml-2 group-hover/btn:translate-x-1 transition-transform" />
          </Button>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6 pt-6">
      {/* Enhanced Header */}
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center">
          <Globe className="h-4 w-4 text-white" />
        </div>
        <div>
          <h2 className="text-2xl font-bold">Browse MCP Specifications</h2>
          <p className="text-muted-foreground">
            Discover and deploy verified MCP servers from our community catalog
          </p>
        </div>
      </div>
      
      <div>
        <div className="space-y-4">
          {/* Enhanced Search */}
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input 
                placeholder="Search servers, tags, or descriptions..." 
                className="pl-10 pr-10 border-2 focus:border-primary/50" 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  onClick={clearSearch}
                  className="absolute right-3 top-3 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            
            <div className="flex gap-2">
              <Button 
                variant="outline"
                size="sm"
                onClick={() => setShowFilters(!showFilters)}
                className={showFilters ? 'bg-primary/10' : ''}
              >
                <Filter className="h-4 w-4 mr-2" />
                Filters
              </Button>
              <Button 
                variant={viewMode === 'list' ? 'default' : 'outline'} 
                size="sm"
                onClick={() => setViewMode('list')}
              >
                <List className="h-4 w-4" />
              </Button>
              <Button 
                variant={viewMode === 'grid' ? 'default' : 'outline'} 
                size="sm"
                onClick={() => setViewMode('grid')}
              >
                <Grid className="h-4 w-4" />
              </Button>
            </div>
          </div>
          
          {/* Enhanced Category Filters */}
          {(showFilters || selectedCategory !== 'All' || searchQuery) && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Categories</span>
                {(selectedCategory !== 'All' || searchQuery) && (
                  <Button variant="ghost" size="sm" onClick={clearSearch}>
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

          {/* Results summary */}
          <div className="flex items-center justify-between text-sm text-muted-foreground pb-2">
            <span>
              {filteredServers.length} {filteredServers.length === 1 ? 'server' : 'servers'} found
              {selectedCategory !== 'All' && ` in ${selectedCategory}`}
              {searchQuery && ` matching "${searchQuery}"`}
            </span>
            <span>{mcpServers.filter(s => s.is_public).length} total available</span>
          </div>
        </div>
        
        <div>
          {isLoading ? (
            <div className="space-y-4">
              <div className={viewMode === 'grid' 
                ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" 
                : "space-y-4"
              }>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className={viewMode === 'grid' ? "p-4 border-2 rounded-xl space-y-4" : "p-4 border-2 rounded-xl"}>
                    <div className="flex items-center gap-4">
                      <Skeleton className="h-12 w-12 rounded-xl" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-40" />
                        <Skeleton className="h-3 w-full" />
                        <div className="flex gap-2">
                          <Skeleton className="h-5 w-12" />
                          <Skeleton className="h-5 w-16" />
                          <Skeleton className="h-5 w-14" />
                        </div>
                      </div>
                      {viewMode === 'list' && (
                        <Skeleton className="h-8 w-24" />
                      )}
                    </div>
                    {viewMode === 'grid' && (
                      <div className="space-y-2">
                        <Skeleton className="h-3 w-full" />
                        <Skeleton className="h-3 w-3/4" />
                        <Skeleton className="h-8 w-full" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : filteredServers.length === 0 ? (
            <div className="text-center py-12">
              <div className="h-16 w-16 mx-auto rounded-2xl bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center mb-4">
                <Search className="h-8 w-8 text-slate-400" />
              </div>
              <h3 className="text-lg font-semibold mb-2">No servers found</h3>
              <p className="text-muted-foreground mb-4">
                {searchQuery || selectedCategory !== 'All' 
                  ? "Try adjusting your search terms or category filter."
                  : "No MCP servers are available in the catalog yet."
                }
              </p>
              {(searchQuery || selectedCategory !== 'All') && (
                <Button variant="outline" onClick={clearSearch}>
                  <X className="h-4 w-4 mr-2" />
                  Clear filters
                </Button>
              )}
            </div>
          ) : (
            <div className={viewMode === 'grid' 
              ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" 
              : "space-y-4"
            }>
              {filteredServers.map(server => 
                viewMode === 'grid' ? renderServerGrid(server) : renderServerCard(server)
              )}
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