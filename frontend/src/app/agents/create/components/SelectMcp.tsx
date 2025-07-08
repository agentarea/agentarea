import { components } from "@/api/schema";
import { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Check, Plus, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SheetClose } from "@/components/ui/sheet";
import { useTranslations } from "next-intl";
import AccordionControl from "./AccordionControl";

type MCPServer = components["schemas"]["MCPServerResponse"];

type SelectMcpProps = {
    mcpServers: MCPServer[];
    onAddTools: (tools: MCPServer[]) => void;
    acceptedTools: string[];
    openToolId?: string | null;
}

export default function SelectMcp({ mcpServers, onAddTools, acceptedTools, openToolId }: SelectMcpProps) {
    const t = useTranslations('AgentsPage');
    const [selectedMcpServers, setSelectedMcpServers] = useState<MCPServer[]>([]);
    const [accordionValue, setAccordionValue] = useState<string>("");

    // Open tool accordion when openToolId changes (e.g., from edit in ToolConfig)
    useEffect(() => {
        if (openToolId) {
            setAccordionValue(`mcp-${openToolId}`);
        }
    }, [openToolId]);
    const handleAddTools = () => {
        onAddTools(selectedMcpServers);
        setSelectedMcpServers([]);
    }
    return (
        <>
            <div className="flex flex-row items-center justify-between">
                <h3 className="note">{t('create.selectedTools', { count: selectedMcpServers.length })}</h3>
                <div className="pl-[10px] flex flex-row items-center gap-1">
                    <SheetClose asChild>
                        <Button size="xs" onClick={handleAddTools}>
                            <Plus className="h-4 w-4" />
                            {t('create.add')}
                        </Button>
                    </SheetClose>
                    {/* <SheetClose asChild>
                        <Button size="xs" variant="outline">
                            <X className="h-4 w-4" />
                            {t('create.cancel')}
                        </Button>
                    </SheetClose> */}
                </div>
            </div>
            <div className="flex flex-col flex-1 overflow-y-auto space-y-2 pb-[40px]">
                {mcpServers.map((server) => {
                    const isSelected = selectedMcpServers.some((s) => s.id === server.id);
                    const isAccepted = acceptedTools.includes(server.id);

                    const handleSelectToggle = (e: React.MouseEvent) => {
                        e.stopPropagation();
                        if (isAccepted) return;

                        if (isSelected) {
                            setSelectedMcpServers(selectedMcpServers.filter((s) => s.id !== server.id));
                        } else {
                            setSelectedMcpServers([...selectedMcpServers, server]);
                        }
                    };

                    return (
                        <div id={`mcp-${server.id}`} key={server.id}>
                        <AccordionControl
                            id={`mcp-${server.id}`}
                            accordionValue={accordionValue}
                            setAccordionValue={setAccordionValue}
                            triggerClassName="group w-max flex flex-row gap-2 py-0 justify-start rotate-0 hover:no-underline [&[data-state=open]>svg]:rotate-90 [&[data-state=open]>svg]:text-accent px-[7px] py-[7px]"
                            chevron={<ChevronRight className="h-4 w-4 shrink-0 text-transparent group-hover:text-accent transition-all duration-300" />}
                            title={
                                <div className="flex flex-row items-center gap-2">
                                    {/* TODO: Add icon */}
                                    <img src="/Icon.svg" className="w-7 h-7" />
                                    <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent dark:group-hover:text-accent group-data-[state=open]:text-accent dark:group-data-[state=open]:text-accent">
                                        {server.name}
                                    </h3>
                                </div>
                            }
                            mainControl={
                                isAccepted ? (
                                    <Badge variant="success" className="h-6">
                                        <Check className="h-4 w-4" />
                                        {t('create.added')}
                                    </Badge>
                                ) : isSelected ? (
                                    <Badge className="h-6">
                                        <Check className="h-4 w-4" />
                                        {t('create.selected')}
                                    </Badge>
                                ) : (
                                    <Badge
                                        variant="light"
                                        onClick={handleSelectToggle}
                                        className="h-6 cursor-pointer border hover:border-primary hover:bg-primary/10 hover:text-primary transition-colors duration-200 flex items-center gap-1"
                                    >
                                        <Plus className="h-4 w-4" />
                                        {t('create.add')}
                                    </Badge>
                                )
                            }
                        >
                            {/* Accordion content */}
                            <div className="p-4 text-sm text-muted-foreground">TEST</div>
                        </AccordionControl>
                        </div>
                    );
                })}
            </div>
        </>
    )
}
