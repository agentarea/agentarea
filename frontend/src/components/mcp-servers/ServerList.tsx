import { BookOpen, Globe, Server } from "lucide-react";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type MCPServer = {
  id: string;
  name: string;
  description: string;
  status: string;
  is_public: boolean;
  updated_at: string;
  docker_image_url?: string;
};

export default function ServerList({
  data,
  searchParams,
}: {
  data: MCPServer[];
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const columns = [
    {
      header: "Provider",
      accessor: "name",
      render: (_: any, server: MCPServer) => (
        <div className="flex items-center gap-2">
          <Server className="h-4 w-4 text-primary" />
          <div>
            <div className="font-medium">{server.name}</div>
            <div className="mt-1 max-w-md text-xs text-muted-foreground">
              {server.description}
            </div>
          </div>
        </div>
      ),
      cellClassName: "font-medium",
    },
    {
      header: "Status",
      accessor: "status",
      render: (value: string) => (
        <Badge variant="secondary" className="text-xs">
          {value}
        </Badge>
      ),
    },
    {
      header: "Type",
      accessor: "docker_image_url",
      render: (value: string, server: MCPServer) => {
        const isExternalServer = value?.includes("http") || false;
        return (
          <Badge
            variant="outline"
            className={
              isExternalServer
                ? "border-purple-200 bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300"
                : "border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
            }
          >
            {isExternalServer ? (
              <Globe className="mr-1 h-3 w-3" />
            ) : (
              <Server className="mr-1 h-3 w-3" />
            )}
            {isExternalServer ? "HTTP" : "Docker"}
          </Badge>
        );
      },
    },
  ];

  return (
    <>
      <div className="mb-4 flex items-center space-x-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <h2 className="text-xl font-semibold">Available MCP Providers</h2>
        <Badge variant="secondary" className="ml-2">
          {data?.length || 0} providers
        </Badge>
      </div>

      <GridAndTableViews
        searchParams={searchParams}
        data={data}
        columns={columns}
        emptyState={
          <EmptyState
            title="No MCP providers available"
            description="MCP providers catalog is empty"
            iconsType="mcp"
            action={{
              label: "Refresh Catalog",
              href: "/mcp-servers",
            }}
          />
        }
        routeChange="/mcp-servers"
        cardContent={(item: any) => (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 font-montserrat text-[16px] font-[500]">
              <Server className="h-4 w-4 text-primary" />
              {item.name}
            </div>
            <div className="line-clamp-2 pt-[10px] text-[14px] opacity-50">
              {item.description}
            </div>
            <div className="mt-2 flex gap-2">
              <Badge variant="secondary" className="text-xs">
                {item.status}
              </Badge>
              {item.is_public && (
                <Badge variant="outline" className="text-xs">
                  Public
                </Badge>
              )}
            </div>
          </div>
        )}
        leftComponent={
          <div className="flex items-center space-x-2">
            <Button variant="outline" size="sm" className="text-xs">
              All Providers
            </Button>
            <Button variant="ghost" size="sm" className="text-xs">
              Self-Hosted
            </Button>
            <Button variant="ghost" size="sm" className="text-xs">
              External
            </Button>
          </div>
        }
      />
    </>
  );
}
