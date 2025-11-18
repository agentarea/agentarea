"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Bot,
  Brain,
  CheckCircle,
  Clock,
  Database,
  Download,
  FileText,
  Filter,
  GitBranch,
  Globe,
  Grid,
  List,
  MessageSquare,
  Search,
  Sparkles,
  Star,
  Wrench,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import Table from "@/components/Table/Table";
import { CreateInstanceDialog } from "./CreateInstanceDialog";
import EmptyState from "@/components/EmptyState";

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
  viewMode?: string;
}

// Enhanced category mapping with icons
const getCategoryIcon = (tags: string[]) => {
  if (
    tags.some(
      (tag) =>
        tag.includes("ai") ||
        tag.includes("llm") ||
        tag.includes("search") ||
        tag.includes("memory")
    )
  )
    return Brain;
  if (
    tags.some(
      (tag) =>
        tag.includes("database") ||
        tag.includes("data") ||
        tag.includes("analytics")
    )
  )
    return Database;
  if (
    tags.some(
      (tag) =>
        tag.includes("git") ||
        tag.includes("repository") ||
        tag.includes("github")
    )
  )
    return GitBranch;
  if (
    tags.some(
      (tag) =>
        tag.includes("web") || tag.includes("browser") || tag.includes("fetch")
    )
  )
    return Globe;
  if (tags.some((tag) => tag.includes("file") || tag.includes("filesystem")))
    return FileText;
  if (
    tags.some(
      (tag) =>
        tag.includes("message") ||
        tag.includes("slack") ||
        tag.includes("gmail")
    )
  )
    return MessageSquare;
  if (
    tags.some((tag) => tag.includes("automation") || tag.includes("puppeteer"))
  )
    return Bot;
  return Wrench;
};

const getCategory = (tags: string[]) => {
  if (
    tags.some(
      (tag) =>
        tag.includes("ai") ||
        tag.includes("llm") ||
        tag.includes("search") ||
        tag.includes("memory")
    )
  )
    return "AI";
  if (
    tags.some(
      (tag) =>
        tag.includes("database") ||
        tag.includes("data") ||
        tag.includes("analytics")
    )
  )
    return "Data";
  if (
    tags.some(
      (tag) =>
        tag.includes("git") ||
        tag.includes("repository") ||
        tag.includes("github")
    )
  )
    return "Dev";
  if (
    tags.some(
      (tag) =>
        tag.includes("web") || tag.includes("browser") || tag.includes("fetch")
    )
  )
    return "Web";
  if (tags.some((tag) => tag.includes("file") || tag.includes("filesystem")))
    return "Files";
  if (
    tags.some(
      (tag) =>
        tag.includes("message") ||
        tag.includes("slack") ||
        tag.includes("gmail")
    )
  )
    return "Messaging";
  return "Tools";
};

// Enhanced category colors
const getCategoryColor = (category: string) => {
  switch (category) {
    case "AI":
      return "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800";
    case "Data":
      return "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/30 dark:text-blue-300 dark:border-blue-800";
    case "Dev":
      return "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-300 dark:border-orange-800";
    case "Web":
      return "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-300 dark:border-green-800";
    case "Files":
      return "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/30 dark:text-yellow-300 dark:border-yellow-800";
    case "Messaging":
      return "bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-950/30 dark:text-pink-300 dark:border-pink-800";
    default:
      return "bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-950/30 dark:text-gray-300 dark:border-gray-800";
  }
};

// Get popularity badge (deterministic based on server ID)
const getPopularityInfo = (server: MCPServer) => {
  // Use deterministic hash from server ID instead of Math.random()
  // This ensures the same result on server and client
  let hash = 0;
  for (let i = 0; i < server.id.length; i++) {
    const char = server.id.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32-bit integer
  }
  // Normalize to 0-1 range
  const deterministicFactor = Math.abs(hash % 100) / 100;
  
  if (deterministicFactor > 0.8)
    return { label: "Popular", variant: "default" as const, icon: Star };
  if (deterministicFactor > 0.6)
    return { label: "New", variant: "secondary" as const, icon: Sparkles };
  return null;
};

export function MCPSpecsSection({
  mcpServers,
  searchParams,
  isLoading = false,
  viewMode = "grid",
}: MCPSpecsSectionProps) {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState(
    (searchParams.search as string) || ""
  );
  const [selectedCategory, setSelectedCategory] = useState(
    (searchParams.category as string) || "All"
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  // Get unique categories from servers (including user-created)
  const categories = useMemo(() => {
    const cats = new Set<string>();
    mcpServers.forEach((server) => {
      cats.add(getCategory(server.tags || []));
    });
    return ["All", ...Array.from(cats).sort()];
  }, [mcpServers]);

  // Filter servers based on search and category (including user-created)
  const filteredServers = useMemo(() => {
    return mcpServers.filter((server) => {
      const matchesSearch =
        server.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        server.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (server.tags || []).some((tag) =>
          tag.toLowerCase().includes(searchQuery.toLowerCase())
        );
      const matchesCategory =
        selectedCategory === "All" ||
        getCategory(server.tags || []) === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [mcpServers, searchQuery, selectedCategory]);

  // Handle opening the configuration dialog
  const handleConfigureInstance = (server: MCPServer) => {
    setSelectedServer(server);
    setDialogOpen(true);
  };

  // Clear search
  const clearSearch = () => {
    setSearchQuery("");
    setSelectedCategory("All");
  };

  // Get status badge component
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <Badge variant="default" className="text-xs">
            <CheckCircle className="mr-1 h-3 w-3" />
            {status}
          </Badge>
        );
      default:
        return (
          <Badge variant="secondary" className="text-xs">
            {status}
          </Badge>
        );
    }
  };

  // Define table columns for servers
  const serverColumns = [
    {
      accessor: "name",
      header: "Name",
      render: (value: string, item: MCPServer) => {
        const popularityInfo = getPopularityInfo(item);
        const category = getCategory(item.tags || []);
        return (
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold">{value}</span>
            {!item.is_public && (
              <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300 shrink-0">
                Custom
              </Badge>
            )}
            {popularityInfo && (
              <Badge variant={popularityInfo.variant} className="text-xs shrink-0">
                {popularityInfo.label}
              </Badge>
            )}
            <Badge className={`border text-xs shrink-0 ${getCategoryColor(category)}`}>
              {category}
            </Badge>
          </div>
        );
      },
    },
    {
      accessor: "description",
      header: "Description",
      render: (value: string) => (
        <span className="truncate text-sm text-muted-foreground">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "version",
      header: "Version",
      render: (value: string) => (
        <span className="font-mono text-xs text-muted-foreground">
          v{value}
        </span>
      ),
    },
    {
      accessor: "tags",
      header: "Tags",
      render: (value: string[]) => (
        <div className="flex flex-wrap gap-1">
          {(value || []).slice(0, 3).map((tag) => (
            <Badge key={tag} variant="outline" className="text-xs">
              {tag}
            </Badge>
          ))}
          {(value || []).length > 3 && (
            <Badge variant="outline" className="text-xs">
              +{(value || []).length - 3}
            </Badge>
          )}
        </div>
      ),
    },
    {
      accessor: "status",
      header: "Status",
      render: (_: string, item: MCPServer) => getStatusBadge(item.status),
    },
    {
      accessor: "updated_at",
      header: "Updated",
      render: (value: string) => (
        <span className="text-xs text-muted-foreground">
          {new Date(value).toLocaleDateString()}
        </span>
      ),
    },
  ];

  // Enhanced List Item
  const renderServerCard = (server: MCPServer) => {
    const IconComponent = getCategoryIcon(server.tags || []);
    const category = getCategory(server.tags || []);
    const categoryColor = getCategoryColor(category);
    const popularityInfo = getPopularityInfo(server);

    return (
      <div
        key={server.id}
        className="group rounded-xl border-2 border-slate-200 bg-white p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg dark:border-slate-700 dark:bg-slate-800/50"
      >
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 flex-1 items-center gap-4">
            {/* Enhanced Icon */}
            <div className="relative flex-shrink-0">
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-xl border-2 ${categoryColor}`}
              >
                <IconComponent className="h-6 w-6" />
              </div>
              {popularityInfo && (
                <div className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary">
                  <popularityInfo.icon className="h-3 w-3 text-white" />
                </div>
              )}
            </div>

            {/* Content */}
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <h3 className="truncate font-semibold text-slate-900 dark:text-white">
                  {server.name}
                </h3>
                {!server.is_public && (
                  <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300">
                    Custom
                  </Badge>
                )}
                {popularityInfo && (
                  <Badge variant={popularityInfo.variant} className="text-xs">
                    {popularityInfo.label}
                  </Badge>
                )}
              </div>

              <p className="mb-2 line-clamp-2 text-sm text-muted-foreground">
                {server.description}
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <Badge className={`border text-xs ${categoryColor}`}>
                  {category}
                </Badge>
                <Badge
                  variant={server.status === "active" ? "default" : "secondary"}
                  className="text-xs"
                >
                  <CheckCircle className="mr-1 h-3 w-3" />
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
          <div className="ml-4 flex flex-shrink-0 items-center gap-2">
            <Button
              size="sm"
              onClick={() => handleConfigureInstance(server)}
              className="group/btn"
            >
              <Download className="mr-2 h-4 w-4 group-hover/btn:animate-bounce" />
              Configure
              <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover/btn:translate-x-1" />
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
        className="group overflow-hidden border-2 border-slate-200 bg-white transition-all duration-300 hover:-translate-y-2 hover:border-primary/50 hover:shadow-2xl dark:border-slate-700 dark:bg-slate-800/50"
      >
        <CardHeader className="relative pb-4">
          {/* Popular badge */}
          {popularityInfo && (
            <div className="absolute right-3 top-3">
              <Badge variant={popularityInfo.variant} className="text-xs">
                <popularityInfo.icon className="mr-1 h-3 w-3" />
                {popularityInfo.label}
              </Badge>
            </div>
          )}

          <div className="mb-3 flex items-center gap-3">
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-xl border-2 transition-transform group-hover:scale-110 ${categoryColor}`}
            >
              <IconComponent className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3 className="line-clamp-1 font-semibold transition-colors group-hover:text-primary">
                  {server.name}
                </h3>
                {!server.is_public && (
                  <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300 shrink-0">
                    Custom
                  </Badge>
                )}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <Badge className={`border text-xs ${categoryColor}`}>
                  {category}
                </Badge>
                <Badge
                  variant={server.status === "active" ? "default" : "secondary"}
                  className="text-xs"
                >
                  {server.status}
                </Badge>
              </div>
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          <p className="mb-4 line-clamp-3 text-sm text-muted-foreground">
            {server.description}
          </p>

          {/* Tags */}
          <div className="mb-4 flex flex-wrap gap-1">
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
          <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span>v{server.version}</span>
            <span>•</span>
            <span>
              Updated {new Date(server.updated_at).toLocaleDateString()}
            </span>
          </div>

          <Button
            size="sm"
            className="group/btn w-full"
            onClick={() => handleConfigureInstance(server)}
          >
            <Download className="mr-2 h-4 w-4 group-hover/btn:animate-bounce" />
            Configure Server
            <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover/btn:translate-x-1" />
          </Button>
        </CardContent>
      </Card>
    );
  };

  // Empty state handling
  if (filteredServers.length === 0) {
    return (
      <EmptyState
        title="No MCP specifications found"
        description="No MCP server instances or specifications are available"
        iconsType="mcp"
      />
    );
  }

  // Render table view
  if (viewMode === "table") {
    return (
      <Table
        data={filteredServers}
        columns={serverColumns}
        onRowClick={(server) => {
          handleConfigureInstance(server);
        }}
      />
    );
  }

  // Render grid/list view (default)
  return (
    <div className="space-y-6">
      <div>
        <div
          className={
            viewMode === "grid"
              ? "grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3"
              : "space-y-4"
          }
        >
          {filteredServers.map((server) =>
            viewMode === "grid"
              ? renderServerGrid(server)
              : renderServerCard(server)
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
