import { components } from "@/api/schema";
import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Accordion } from "@/components/ui/accordion";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Badge } from "@/components/ui/badge";
import { Plus } from "lucide-react";

type MCPServer = components["schemas"]["MCPServerResponse"];

type SelectMcpProps = {
    mcpServers: MCPServer[];
    onAddTools: (tools: MCPServer[]) => void;
    onRemoveTool: (serverId: string) => void;
    acceptedTools: string[];
    openToolId?: string | null;
}

export default function SelectMcp({ mcpServers, onAddTools, onRemoveTool, acceptedTools, openToolId }: SelectMcpProps) {
    const t = useTranslations('AgentsPage');
    const [accordionValue, setAccordionValue] = useState<string>("");

    // Open tool accordion when openToolId changes (e.g., from edit in ToolConfig)
    useEffect(() => {
        if (openToolId) {
            setAccordionValue(`mcp-${openToolId}`);
        } else {
            setAccordionValue("");
        }
    }, [openToolId]);
    return (
        <Accordion 
            type="single" 
            collapsible 
            className="flex flex-col flex-1 overflow-y-auto space-y-2 pb-[40px]"
            value={accordionValue}
            onValueChange={setAccordionValue}
        >
            {mcpServers.map((server) => {
                const isAccepted = acceptedTools.includes(server.id);

                const controls = isAccepted ? (
                    <Badge
                        variant="destructive"
                        onClick={() => onRemoveTool(server.id)}
                        className="cursor-pointer border hover:border-destructive"
                    >
                        ✕ {t('create.remove')}
                    </Badge>
                ) : (
                    <Badge
                        variant="light"
                        onClick={() => onAddTools([server])}
                        className="cursor-pointer border hover:border-primary hover:text-primary dark:hover:bg-primary dark:hover:text-white"
                    >
                        <Plus className="h-4 w-4" />
                        {t('create.add')}
                    </Badge>
                );

                return (
                    <CardAccordionItem
                        key={server.id}
                        value={`mcp-${server.id}`}
                        id={`mcp-${server.id}`}
                        title={server.name}
                        iconSrc="/Icon.svg" // TODO: replace with real icon
                        controls={controls}
                    >
                        {/* Accordion content */}
                        <div className="p-4 text-sm text-muted-foreground">TEST</div>
                    </CardAccordionItem>
                );
            })}
        </Accordion>
    );
}
