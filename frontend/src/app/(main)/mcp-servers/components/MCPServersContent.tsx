import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { getTranslations } from 'next-intl/server';
import { MyMCPsSection } from "./MyMCPsSection";
import { MCPSpecsSection } from "./MCPSpecsSection";
import EmptyState from "@/components/EmptyState";

interface MCPInstance {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  endpoint_url?: string;
  created_at: string;
  server_spec_id?: string | null;
  json_spec?: any;
}

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

interface MCPServersContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function MCPServersContent({ 
    searchQuery = "", 
    viewMode = "grid" 
}: MCPServersContentProps) {
    const t = await getTranslations("MCPServersPage");

    // Fetch MCP servers and instances
    const [serversResponse, instancesResponse] = await Promise.all([
        listMCPServers(),
        listMCPServerInstances()
    ]);

    // Handle API errors
    if (serversResponse.error || instancesResponse.error) {
        const serversError = serversResponse.error as any;
        const instancesError = instancesResponse.error as any;
       
        return (
            <div className="text-center py-10">
                <p className="text-red-500">
                    Error loading data: {
                        serversError?.detail?.[0]?.msg || 
                        instancesError?.detail?.[0]?.msg ||
                        'Unknown error occurred'
                    }
                </p>
            </div>
        );
    }

    const mcpServers = (serversResponse.data || []) as MCPSpec[];
    const mcpInstances = (instancesResponse.data || []) as MCPInstance[];

    // Filter MCP instances based on search query
    let filteredInstances = mcpInstances;
    if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        filteredInstances = mcpInstances.filter(instance => 
            instance.name?.toLowerCase().includes(query) ||
            instance.description?.toLowerCase().includes(query) ||
            instance.endpoint_url?.toLowerCase().includes(query)
        );
    }

    // Filter MCP specs based on search query
    let filteredServers = mcpServers;
    if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        filteredServers = mcpServers.filter(server => 
            server.name?.toLowerCase().includes(query) ||
            server.description?.toLowerCase().includes(query) ||
            (server.tags || []).some(tag => tag.toLowerCase().includes(query))
        );
    }

    // Check for empty states
    const hasNoInstances = mcpInstances.length === 0;
    const hasNoServers = mcpServers.filter(s => s.is_public).length === 0;
    const hasNoData = hasNoInstances && hasNoServers;
    const hasNoResults = filteredInstances.length === 0 && filteredServers.filter(s => s.is_public).length === 0 && !hasNoData;

    // Handle global empty states
    if (hasNoData) {
        return (
            <EmptyState 
                title="No MCP servers found"
                description="No MCP server instances or specifications are available"
                iconsType="mcp"
            />
        );
    }

    if (hasNoResults) {
        return (
            <EmptyState 
                title="No matching servers"
                description={`No servers match your search query: "${searchQuery}"`}
                iconsType="mcp"
            />
        );
    }

    // Render both sections
    return (
        <div className="space-y-8">
            {/* My Active Servers Section */}
            <div id="my-mcps">
                <h4 className="mb-3 uppercase text-xs text-muted-foreground/80">
                    My Active Servers ({filteredInstances.length})
                </h4>
                <MyMCPsSection 
                    mcpInstances={filteredInstances} 
                    viewMode={viewMode}
                    searchQuery={searchQuery}
                    hasNoData={hasNoInstances}
                />
            </div>
            
            {/* Browse MCP Specifications Section */}
            <div id="specs-section">
                <h4 className="mb-3 uppercase text-xs text-muted-foreground/80">
                    Browse MCP Specifications ({filteredServers.filter(s => s.is_public).length})
                </h4>
                <MCPSpecsSection
                    mcpServers={filteredServers}
                    searchParams={{ search: searchQuery }}
                />
            </div>
        </div>
    );
}
