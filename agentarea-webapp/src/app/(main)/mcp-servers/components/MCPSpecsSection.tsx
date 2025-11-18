"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import Table from "@/components/Table/Table";
import { CreateInstanceDialog } from "./CreateInstanceDialog";
import EmptyState from "@/components/EmptyState";
import { MCPServerSpecCard, MCPSpec } from "./MCPCard";

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
  updated_at: string;
}

interface MCPSpecsSectionProps {
  mcpServers: MCPServer[];
  searchParams: { [key: string]: string | string[] | undefined };
  viewMode?: string;
}

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

export function MCPSpecsSection({
  mcpServers,
  searchParams,
  viewMode = "grid",
}: MCPSpecsSectionProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);

  const searchQuery = (searchParams.search as string) || "";
  const selectedCategory = (searchParams.category as string) || "All";

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

  const handleConfigureInstance = (server: MCPServer | MCPSpec) => {
    setSelectedServer(server as MCPServer);
    setDialogOpen(true);
  };

  const serverColumns = [
    {
      accessor: "name",
      header: "Name",
      render: (value: string, item: MCPServer) => {
        const category = getCategory(item.tags || []);
        return (
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold">{value}</span>
            {!item.is_public && (
              <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300 shrink-0">
                Custom
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
      accessor: "updated_at",
      header: "Updated",
      render: (value: string) => (
        <span className="text-xs text-muted-foreground">
          {new Date(value).toLocaleDateString()}
        </span>
      ),
    },
  ];

  if (filteredServers.length === 0) {
    return (
      <EmptyState
        title="No MCP specifications found"
        description="No MCP server instances or specifications are available"
        iconsType="mcp"
      />
    );
  }

  if (viewMode === "table") {
    return (
      <Table
        data={filteredServers}
        columns={serverColumns}
        onRowClick={handleConfigureInstance}
      />
    );
  }
  return (
    <>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {filteredServers.map((server) => (
          <MCPServerSpecCard
            key={server.id}
            server={server as MCPSpec}
            onConfigure={(server) => handleConfigureInstance(server as MCPSpec)}
          />
        ))}
      </div>

      <CreateInstanceDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mcpServer={selectedServer}
      />
    </>
  );
}
