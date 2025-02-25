"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Search,
  Filter,
  ArrowUpDown,
  RefreshCw,
  Settings,
  Plus,
  Lock,
  Building2,
  LayoutGrid,
  Table as TableIcon,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  Database,
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRouter } from "next/navigation";
import { sourcesApi, SourceResponse } from '@/api/sources';
import { Skeleton } from "@/components/ui/skeleton";
import { motion } from "framer-motion";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SourceStatus, SourceType } from "@/types/source";

type FilterType = "all" | "setup" | "available" | "own" | "delegated" | "private" | "shared";

// Status icon mapping
const StatusIcon = ({ status }: { status: string }) => {
  switch (status) {
    case "active":
    case "connected":
      return <CheckCircle2 className="h-4 w-4 text-green-500" />;
    case "inactive":
    case "disconnected":
      return <XCircle className="h-4 w-4 text-red-500" />;
    case "error":
      return <AlertCircle className="h-4 w-4 text-amber-500" />;
    case "in_progress":
      return <Clock className="h-4 w-4 text-blue-500" />;
    default:
      return null;
  }
};

// Skeleton loader for cards
const SourceCardSkeleton = () => (
  <Card className="p-6 hover:shadow-lg transition-shadow duration-200">
    <div className="flex items-start justify-between mb-4">
      <div className="flex items-center gap-3">
        <Skeleton className="h-12 w-12 rounded-lg" />
        <div>
          <Skeleton className="h-5 w-40 mb-2" />
          <Skeleton className="h-4 w-20" />
        </div>
      </div>
      <Skeleton className="h-6 w-24 rounded-full" />
    </div>
    <Skeleton className="h-4 w-full mb-4" />
    <Skeleton className="h-4 w-3/4 mb-4" />
    <div className="flex flex-col gap-2 mb-4">
      <div className="flex items-center gap-2">
        <Skeleton className="h-4 w-4" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Skeleton className="h-6 w-16 rounded-full" />
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-14 rounded-full" />
      </div>
    </div>
    <div className="flex justify-between items-center">
      <div>
        <Skeleton className="h-4 w-20 mb-2" />
        <Skeleton className="h-4 w-24" />
      </div>
      <div className="text-right">
        <Skeleton className="h-4 w-20 mb-2" />
        <Skeleton className="h-4 w-16" />
      </div>
    </div>
  </Card>
);

// Helper function to get background color for source type
const getTypeColor = (type: SourceType) => {
  const colors: Record<string, string> = {
    [SourceType.DATABASE]: "bg-blue-100 text-blue-800",
    [SourceType.API]: "bg-purple-100 text-purple-800",
    [SourceType.FILE]: "bg-green-100 text-green-800",
    [SourceType.STREAM]: "bg-amber-100 text-amber-800",
  };
  return colors[type] || "bg-gray-100 text-gray-800";
};

// Helper function to get background color for source status
const getStatusColor = (status: SourceStatus) => {
  const colors: Record<string, string> = {
    [SourceStatus.ACTIVE]: "bg-green-100 text-green-800",
    [SourceStatus.INACTIVE]: "bg-red-100 text-red-800",
    [SourceStatus.ERROR]: "bg-amber-100 text-amber-800",
  };
  return colors[status] || "bg-gray-100 text-gray-800";
};

export default function SourcesBrowsePage() {
  const router = useRouter();
  const [viewMode, setViewMode] = React.useState<"grid" | "table">("grid");
  const [selectedFilter, setSelectedFilter] = React.useState<FilterType>("all");
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const handleViewModeChange = (value: string) => {
    setViewMode(value as "grid" | "table");
  };

  const filteredSources = React.useMemo(() => {
    // First apply category filters
    let filtered = [...sources];
    
    // Then apply search filter if there is a search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(source => 
        source.name.toLowerCase().includes(query) || 
        source.description.toLowerCase().includes(query) ||
        source.type.toLowerCase().includes(query)
      );
    }
    
    return filtered;
  }, [sources, selectedFilter, searchQuery]);

  useEffect(() => {
    loadSources();
  }, []);

  async function loadSources() {
    try {
      const data = await sourcesApi.listSources();
      setSources(data);
    } catch (err) {
      setError('Failed to load sources');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    setLoading(true);
    await loadSources();
  }

  // Animation variants for list items
  const container = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1
      }
    }
  };
  
  const item = {
    hidden: { y: 20, opacity: 0 },
    show: { y: 0, opacity: 1 }
  };

  // Helper function to get metadata value with fallback
  const getMetadataValue = (source: SourceResponse, key: string, fallback: string = 'Unknown') => {
    return source.metadata && source.metadata[key] ? source.metadata[key] : fallback;
  };

  // Extract resource types from metadata if available
  const getResourceTypes = (source: SourceResponse) => {
    if (source.metadata && source.metadata.resourceTypes && Array.isArray(source.metadata.resourceTypes)) {
      return source.metadata.resourceTypes as string[];
    }
    return [];
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold bg-gradient-to-r from-primary to-primary/70 bg-clip-text text-transparent">Data Sources</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your connected data sources and integrations
          </p>
        </div>
        <div className="flex gap-4">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  variant="outline" 
                  className="flex items-center gap-2"
                  onClick={handleRefresh}
                  disabled={loading}
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                  <span className="hidden sm:inline">Refresh</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Refresh all sources</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          
          <Button 
            className="flex items-center gap-2 bg-gradient-to-r from-primary to-primary/80 hover:from-primary/90 hover:to-primary/70"
            onClick={() => router.push('/sources/new')}
          >
            <Plus className="h-5 w-5" />
            <span className="hidden sm:inline">Add Source</span>
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-6 mb-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div className="flex flex-col sm:flex-row gap-4 flex-1 w-full">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
              <Input
                placeholder="Search sources..."
                className="pl-10"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="flex items-center gap-2">
                    <Filter className="h-4 w-4" />
                    <span className="hidden sm:inline">Filter</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setSelectedFilter("all")}>
                    All Sources
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSelectedFilter("setup")}>
                    Setup Ready
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSelectedFilter("available")}>
                    Available
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSelectedFilter("own")}>
                    Own Sources
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSelectedFilter("delegated")}>
                    Delegated
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="flex items-center gap-2">
                    <ArrowUpDown className="h-4 w-4" />
                    <span className="hidden sm:inline">Sort</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem>Name (A-Z)</DropdownMenuItem>
                  <DropdownMenuItem>Name (Z-A)</DropdownMenuItem>
                  <DropdownMenuItem>Newest First</DropdownMenuItem>
                  <DropdownMenuItem>Oldest First</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
          <Tabs value={viewMode} onValueChange={handleViewModeChange} className="w-auto">
            <TabsList className="grid w-20 grid-cols-2">
              <TabsTrigger value="grid" className="flex items-center justify-center">
                <LayoutGrid className="h-4 w-4" />
              </TabsTrigger>
              <TabsTrigger value="table" className="flex items-center justify-center">
                <TableIcon className="h-4 w-4" />
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-secondary scrollbar-track-transparent">
          <Badge 
            variant={selectedFilter === "all" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80 whitespace-nowrap"
            onClick={() => setSelectedFilter("all")}
          >
            All Sources
          </Badge>
          <Badge 
            variant={selectedFilter === "setup" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80 whitespace-nowrap"
            onClick={() => setSelectedFilter("setup")}
          >
            Setup Ready
          </Badge>
          <Badge 
            variant={selectedFilter === "available" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80 whitespace-nowrap"
            onClick={() => setSelectedFilter("available")}
          >
            Available
          </Badge>
          <Badge 
            variant={selectedFilter === "own" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80 whitespace-nowrap"
            onClick={() => setSelectedFilter("own")}
          >
            Own Sources
          </Badge>
          <Badge 
            variant={selectedFilter === "delegated" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80 whitespace-nowrap"
            onClick={() => setSelectedFilter("delegated")}
          >
            Delegated
          </Badge>
        </div>
      </div>

      {loading ? (
        viewMode === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[...Array(6)].map((_, i) => (
              <SourceCardSkeleton key={i} />
            ))}
          </div>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Organization</TableHead>
                  <TableHead>Resources</TableHead>
                  <TableHead>Last Sync</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...Array(5)].map((_, i) => (
                  <TableRow key={i}>
                    <TableCell><Skeleton className="h-8 w-40" /></TableCell>
                    <TableCell><Skeleton className="h-6 w-20" /></TableCell>
                    <TableCell><Skeleton className="h-6 w-24" /></TableCell>
                    <TableCell><Skeleton className="h-6 w-32" /></TableCell>
                    <TableCell><Skeleton className="h-6 w-40" /></TableCell>
                    <TableCell><Skeleton className="h-6 w-24" /></TableCell>
                    <TableCell><Skeleton className="h-8 w-20" /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-2" />
          <h3 className="text-lg font-medium text-red-800">Failed to load sources</h3>
          <p className="text-red-600">{error}</p>
          <Button 
            variant="outline" 
            className="mt-4 border-red-300 text-red-700 hover:bg-red-50"
            onClick={handleRefresh}
          >
            Try Again
          </Button>
        </div>
      ) : filteredSources.length === 0 ? (
        <div className="text-center py-12 border rounded-lg bg-muted/20">
          <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center mb-4">
            <Database className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-xl font-medium mb-2">No sources found</h3>
          <p className="text-muted-foreground mb-6">
            {searchQuery 
              ? "No sources match your search criteria. Try a different search term."
              : "You don't have any sources yet. Add your first source to get started."}
          </p>
          <Button 
            onClick={() => router.push('/sources/new')}
            className="flex items-center gap-2 mx-auto"
          >
            <Plus className="h-4 w-4" />
            Add Your First Source
          </Button>
        </div>
      ) : viewMode === "grid" ? (
        <motion.div 
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          variants={container}
          initial="hidden"
          animate="show"
        >
          {filteredSources.map((source) => (
            <motion.div key={source.source_id} variants={item}>
              <Card 
                className="overflow-hidden hover:shadow-lg transition-all duration-300 cursor-pointer group border border-border/50 hover:border-primary/20"
                onClick={() => router.push(`/sources/${source.source_id}`)}
              >
                <CardContent className="p-6">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className={`h-12 w-12 rounded-lg flex items-center justify-center ${getTypeColor(source.type)}`}>
                        <Database className="h-6 w-6" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold group-hover:text-primary transition-colors">{source.name}</h3>
                          {getMetadataValue(source, 'visibility') === "private" && (
                            <Lock className="h-4 w-4 text-muted-foreground" />
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-1 rounded-full ${getTypeColor(source.type)}`}>
                            {source.type}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${getStatusColor(source.status)}`}>
                      <StatusIcon status={source.status} />
                      <span className="text-sm capitalize">{source.status?.replace('_', ' ')}</span>
                    </div>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4 line-clamp-2">{source.description}</p>
                  <div className="flex flex-col gap-2 mb-4">
                    <div className="flex items-center gap-2">
                      <Building2 className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm">{getMetadataValue(source, 'organization', 'Unknown')}</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {getResourceTypes(source).map((type) => (
                        <Badge key={type} variant="secondary" className="bg-secondary/50">
                          {type}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex justify-between items-center text-sm">
                    <div>
                      <p className="font-medium">Last Sync</p>
                      <p className="text-muted-foreground">{getMetadataValue(source, 'lastSync', 'Never')}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-medium">Data Points</p>
                      <p className="text-muted-foreground">{getMetadataValue(source, 'dataPoints', '0')}</p>
                    </div>
                  </div>
                </CardContent>
                <CardFooter className="px-6 py-3 bg-muted/10 border-t flex justify-end gap-2" onClick={e => e.stopPropagation()}>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon" className="rounded-full hover:bg-secondary/80">
                          <RefreshCw className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Refresh source</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon" className="rounded-full hover:bg-secondary/80">
                          <Settings className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Source settings</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </CardFooter>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table>
            <TableHeader className="bg-muted/30">
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Organization</TableHead>
                <TableHead className="hidden lg:table-cell">Resources</TableHead>
                <TableHead className="hidden md:table-cell">Last Sync</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredSources.map((source, index) => (
                <motion.tr
                  key={source.source_id}
                  className="cursor-pointer hover:bg-secondary/30 data-[state=selected]:bg-secondary"
                  onClick={() => router.push(`/sources/${source.source_id}`)}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${getTypeColor(source.type)}`}>
                        <Database className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="font-medium">{source.name}</div>
                        <div className="text-sm text-muted-foreground line-clamp-1 max-w-[200px]">
                          {source.description}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={getTypeColor(source.type)}>
                      {source.type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${getStatusColor(source.status)}`}>
                      <StatusIcon status={source.status} />
                      <span className="text-sm capitalize">{source.status?.replace('_', ' ')}</span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{getMetadataValue(source, 'organization', 'Unknown')}</TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <div className="flex flex-wrap gap-1 max-w-[200px]">
                      {getResourceTypes(source).slice(0, 3).map((type) => (
                        <Badge key={type} variant="secondary" className="bg-secondary/50">
                          {type}
                        </Badge>
                      ))}
                      {getResourceTypes(source).length > 3 && (
                        <Badge variant="outline">+{getResourceTypes(source).length - 3}</Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{getMetadataValue(source, 'lastSync', 'Never')}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-2">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8">
                              <RefreshCw className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Refresh source</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8">
                              <Settings className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Source settings</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  </TableCell>
                </motion.tr>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
} 