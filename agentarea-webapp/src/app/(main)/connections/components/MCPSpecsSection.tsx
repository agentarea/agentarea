"use client";

import { useCallback, useMemo } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";
import Table from "@/components/Table/Table";
import EmptyState from "@/components/EmptyState";
import { MCPServerSpecCard } from "./MCPCard";
import { MCPServer } from "../types";
import { getMCPServerCategory, getCategoryColorClasses, getConnectionType } from "../utils";
import type { PaginatedResponseMcpServerResponse } from "@/api/client/types.gen";
import { useInfiniteList } from "@/hooks/useInfiniteList";
import { listMCPServersAction as listMCPServers } from "@/lib/server-actions";

interface MCPSpecsSectionProps {
  searchParams: { [key: string]: string | string[] | undefined };
  viewMode?: string;
}

export function MCPSpecsSection({
  searchParams,
  viewMode = "grid",
}: MCPSpecsSectionProps) {
  const t = useTranslations("MCPServersPage.table");
  const tPage = useTranslations("MCPServersPage");
  const router = useRouter();

  const searchQuery = (searchParams.search as string) || "";
  const selectedCategory = (searchParams.category as string) || "All";
  const selectedType = (searchParams.type as string) || "All";

  const fetchPage = useCallback(
    async (params: { page: number; page_size: number; search?: string }) => {
      const response = await listMCPServers({
        page: params.page,
        page_size: params.page_size,
        search: params.search,
      });
      const data = response.data as PaginatedResponseMcpServerResponse | null;
      return {
        items: (data?.items || []) as MCPServer[],
        total: data?.total || 0,
        has_next: data?.has_next || false,
      };
    },
    []
  );

  const {
    items: servers,
    total,
    isLoading,
    isFetchingMore,
    hasMore,
    error,
    sentinelRef,
  } = useInfiniteList<MCPServer>({
    fetchPage,
    pageSize: 50,
    search: searchQuery || undefined,
  });

  // Client-side category + type filtering (applied on top of server-side search)
  const filteredServers = useMemo(() => {
    let result = servers;
    if (selectedCategory !== "All") {
      result = result.filter(
        (server) => getMCPServerCategory(server.tags || []) === selectedCategory
      );
    }
    if (selectedType !== "All") {
      result = result.filter(
        (server) => getConnectionType(server) === selectedType
      );
    }
    return result;
  }, [servers, selectedCategory, selectedType]);

  const handleConfigureInstance = (server: MCPServer) => {
    router.push(`/connections/create/${server.id}`);
  };

  const serverColumns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string, item: MCPServer) => {
        const category = getMCPServerCategory(item.tags || []);
        const iconSrc = (item.json_spec?.['icons'] as Array<{ src: string }> | undefined)?.[0]?.src;
        const title = (item.json_spec?.['title'] as string | undefined) || value;
        return (
          <div className="flex items-center gap-2">
            {iconSrc && (
              <Image src={iconSrc} alt="" width={20} height={20} className="h-5 w-5 rounded object-contain shrink-0" />
            )}
            <span className="truncate font-semibold">{title}</span>
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-10 text-center">
        <p className="text-destructive">Error loading servers: {error}</p>
      </div>
    );
  }

  return (
    <>
      <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
        {tPage("browseSpecifications")} ({total})
      </h4>

      {/* FilterChips disabled — client-side filtering on paginated data is unreliable.
         TODO: move filtering to server-side API params.
      <div className="mb-4">
        <FilterChips />
      </div>
      */}

      {filteredServers.length === 0 ? (
        <EmptyState
          title="No MCP specifications found"
          description="No MCP server specifications match your search"
          iconsType="mcp"
        />
      ) : viewMode === "table" ? (
        <>
          <Table
            data={filteredServers}
            columns={serverColumns}
            onRowClick={handleConfigureInstance}
          />
          {/* Sentinel for infinite scroll */}
          {hasMore && (
            <div ref={sentinelRef} className="flex justify-center py-4">
              {isFetchingMore && (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {filteredServers.map((server) => (
              <MCPServerSpecCard
                key={server.id}
                server={server}
                onConfigure={handleConfigureInstance}
              />
            ))}
          </div>
          {/* Sentinel for infinite scroll */}
          {hasMore && (
            <div ref={sentinelRef} className="flex justify-center py-4">
              {isFetchingMore && (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
