import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Agent } from "@/types/agent";
import { getToolsForDisplay } from "@/utils/toolsDisplay";
import { AlertCircle } from "lucide-react";
import { useTranslations } from "next-intl";

interface Props {
  agent: Agent;
}

export default function ToolsDisplay({ agent }: Props) {
  const tools = getToolsForDisplay(agent);
  const t = useTranslations("AgentsPage");

  if (tools.length === 0) {
    return (
      <Badge size="sm" variant="yellow">
        <AlertCircle className="mr-1 h-3 w-3" />
        {t("noToolsConf")}
      </Badge>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex flex-wrap gap-1">
        {tools.map((tool, index) => (
          <Tooltip key={index}>
            <TooltipTrigger asChild>
              <div className="group relative">
                <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-zinc-100 p-1 transition-colors hover:bg-primary/20 dark:bg-zinc-500">
                  <img
                    src={tool.imageUrl}
                    alt={tool.name}
                    className="rounded-sm"
                    onError={(e) => {
                      // Fallback to a default icon if image fails to load
                      const target = e.target as HTMLImageElement;
                      target.src =
                        "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0IiByeD0iNCIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNMTIgNkwxNCA4TDEyIDEwTDEwIDhMMTIgNloiIGZpbGw9IiM5OTk5OTkiLz4KPHBhdGggZD0iTTEyIDE0TDE0IDE2TDEyIDE4TDEwIDE2TDEyIDE0WiIgZmlsbD0iIzk5OTk5OSIvPgo8L3N2Zz4K";
                    }}
                  />
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="top" align="center">
              {tool.type === "mcp" ? `MCP Server: ${tool.name}` : tool.name}
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}
