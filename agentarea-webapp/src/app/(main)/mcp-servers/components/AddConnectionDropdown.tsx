"use client";

import { useRouter } from "next/navigation";
import { Plus, Server, FileJson2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function AddConnectionDropdown() {
  const router = useRouter();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button className="shrink-0 gap-2" size="xs" data-test="new-connection-button">
          <Plus className="mr-1 h-4 w-4" />
          Add Connection
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => router.push("/mcp-servers/add")}>
          <Server className="mr-2 h-4 w-4" />
          MCP Server
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => router.push("/mcp-servers/add-openapi")}>
          <FileJson2 className="mr-2 h-4 w-4" />
          OpenAPI Connection
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
