"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import Table from "@/components/Table/Table";
import EmptyState from "@/components/EmptyState";
import { MCPServerSpecCard } from "./MCPCard";
import { MCPServer } from "../types";
import { getMCPServerCategory, getCategoryColorClasses } from "../utils";

interface MCPSpecsSectionProps {
  mcpServers: MCPServer[];
  searchParams: { [key: string]: string | string[] | undefined };
  viewMode?: string;
}

export function MCPSpecsSection({
  mcpServers,
  searchParams,
  viewMode = "grid",
}: MCPSpecsSectionProps) {
  const t = useTranslations("MCPServersPage.table");
  const router = useRouter();

  const searchQuery = (searchParams.search as string) || "";
  const selectedCategory = (searchParams.category as string) || "All";

  const filteredServers = useMemo(() => {
    const query = searchQuery.toLowerCase();
    return mcpServers.filter((server) => {
      const matchesSearch =
        server.name.toLowerCase().includes(query) ||
        server.description.toLowerCase().includes(query) ||
        (server.tags || []).some((tag) =>
          tag.toLowerCase().includes(query)
        );
      const matchesCategory =
        selectedCategory === "All" ||
        getMCPServerCategory(server.tags || []) === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [mcpServers, searchQuery, selectedCategory]);

  const handleConfigureInstance = (server: MCPServer) => {
    router.push(`/mcp-servers/create/${server.id}`);
  };

  const serverColumns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string, item: MCPServer) => {
        const category = getMCPServerCategory(item.tags || []);
        return (
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold">{value}</span>
            {!item.is_public && (
              <Badge
                variant="outline"
                className="text-xs border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300 shrink-0"
              >
                Custom
              </Badge>
            )}
            <Badge
              className={`border text-xs shrink-0 ${getCategoryColorClasses(category)}`}
            >
              {category}
            </Badge>
          </div>
        );
      },
    },
    {
      accessor: "description",
      header: t("description"),
      render: (value: string) => (
        <span className="truncate text-sm text-muted-foreground">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "version",
      header: t("version"),
      render: (value: string) => (
        <span className="font-mono text-xs text-muted-foreground">
          v{value}
        </span>
      ),
    },
    {
      accessor: "updated_at",
      header: t("updated"),
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
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {filteredServers.map((server) => (
        <MCPServerSpecCard
          key={server.id}
          server={server}
          onConfigure={handleConfigureInstance}
        />
      ))}
    </div>
  );
}
