"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import CollectionView, {
  type CollectionItem,
  shortAge,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { useInfiniteList } from "@/hooks/useInfiniteList";
import { listMCPServersAction as listMCPServers } from "@/lib/server-actions";
import { MCPServer } from "../types";
import { getConnectionType, getMCPServerCategory } from "../utils";

interface MCPSpecsSectionProps {
  searchParams: { [key: string]: string | string[] | undefined };
  viewMode?: string;
}

export function MCPSpecsSection({
  searchParams,
  viewMode = "grid",
}: MCPSpecsSectionProps) {
  const tPage = useTranslations("MCPServersPage");

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
      const data = response.data as any;
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

  const items = useMemo<CollectionItem[]>(
    () =>
      filteredServers.map((server) => {
        const category = getMCPServerCategory(server.tags || []);
        const iconSrc = (server as any).json_spec?.icons?.[0]?.src as
          | string
          | undefined;
        const title = (server as any).json_spec?.title || server.name;
        return {
          id: server.id,
          color: "#5e6ad2",
          icon: (
            <img
              src={iconSrc || "/mcp.svg"}
              alt=""
              aria-hidden="true"
              className="h-4 w-4 rounded object-contain"
            />
          ),
          title,
          description: server.description,
          href: `/mcp-servers/create/${server.id}`,
          badges: [
            { label: category, color: "#8a8f98" },
            ...(server.is_public
              ? []
              : [{ label: "Custom", color: "#d97706" }]),
          ],
          meta: (
            <span className="flex items-center gap-2">
              {server.version && (
                <span className="font-mono">v{server.version}</span>
              )}
              <span>{shortAge((server as any).updated_at)}</span>
            </span>
          ),
        };
      }),
    [filteredServers]
  );

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

      <CollectionView
        view={viewMode === "table" ? "list" : "grid"}
        items={items}
        bleed
        emptyState={
          <EmptyState
            title="No MCP specifications found"
            description="No MCP server specifications match your search"
            iconsType="mcp"
          />
        }
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
  );
}
