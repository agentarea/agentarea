import { Agent } from "@/types/agent";
import { getToolsForDisplay } from "@/utils/toolsDisplay";

interface Props {
    agent: Agent;
}

export default function ToolsDisplay({ agent }: Props) {
    const tools = getToolsForDisplay(agent);

    if (tools.length === 0) {
        return <span className="text-gray-500">No tools configured</span>;
    }

    return (
        <div className="flex flex-wrap gap-1">
            {tools.map((tool, index) => (
                <div
                    key={index}
                    className="relative group"
                    title={tool.type === 'mcp' ? `MCP Server: ${tool.name}` : tool.name}
                >
                    <div className="w-6 h-6 p-1 bg-zinc-100 dark:bg-zinc-500 rounded-lg flex items-center justify-center hover:bg-primary/20 transition-colors p-1">
                        <img
                            src={tool.imageUrl}
                            alt={tool.name}
                            className="rounded-sm"
                            onError={(e) => {
                                // Fallback to a default icon if image fails to load
                                const target = e.target as HTMLImageElement;
                                target.src = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0IiByeD0iNCIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNMTIgNkwxNCA4TDEyIDEwTDEwIDhMMTIgNloiIGZpbGw9IiM5OTk5OTkiLz4KPHBhdGggZD0iTTEyIDE0TDE0IDE2TDEyIDE4TDEwIDE2TDEyIDE0WiIgZmlsbD0iIzk5OTk5OSIvPgo8L3N2Zz4K";
                            }}
                        />
                    </div>
                    {/* Tooltip */}
                    <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded-md opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap z-10">
                        {tool.type === 'mcp' ? `MCP Server: ${tool.name}` : tool.name}
                        <div className="absolute top-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>
                    </div>
                </div>
            ))}
        </div>
    );
}
