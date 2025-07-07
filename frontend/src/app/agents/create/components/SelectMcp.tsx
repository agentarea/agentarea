import { components } from "@/api/schema";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Check, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SheetClose } from "@/components/ui/sheet";
import { useTranslations } from "next-intl";

type MCPServer = components["schemas"]["MCPServerResponse"];

type SelectMcpProps = {
    mcpServers: MCPServer[];
    onAddTools: (tools: MCPServer[]) => void;
    acceptedTools: string[];
}

export default function SelectMcp({ mcpServers, onAddTools, acceptedTools }: SelectMcpProps) {
    const t = useTranslations('AgentsPage');
    const [selectedMcpServers, setSelectedMcpServers] = useState<MCPServer[]>([]);
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
            <div className="flex flex-col flex-1 overflow-y-auto space-y-1 pb-[40px]">
                {
                    mcpServers.map((server) => (
                        <div key={server.id} className="flex flex-row items-center justify-between cursor-pointer group hover:bg-primary/20 dark:hover:bg-accent-foreground/20 px-[7px] py-[7px] rounded-md"
                            onClick={() => {
                                if (acceptedTools.includes(server.id)) {
                                    return;
                                }
                                if (selectedMcpServers.includes(server)) {
                                    setSelectedMcpServers(selectedMcpServers.filter((s) => s.id !== server.id));
                                } else {
                                    setSelectedMcpServers([...selectedMcpServers, server]);
                                }
                            }}
                        >
                            <div className="flex flex-row items-center gap-2">
                                {/* TODO: Add icon */}
                                <img src="/Icon.svg" className="w-7 h-7" />
                                <h3 className="text-sm font-medium">{server.name}</h3>
                            </div>
                            {
                                acceptedTools.includes(server.id) ? (
                                    <Badge variant="success" >
                                        <Check className="h-4 w-4" />
                                        {t('create.added')}
                                    </Badge>
                                )
                                    : selectedMcpServers.includes(server) ? (
                                        <Badge>
                                            <Check className="h-4 w-4" />
                                            {t('create.selected')}
                                        </Badge>
                                    ) : (
                                        <Badge variant="light" className="group-hover:inline-flex hidden">
                                            <Plus className="h-4 w-4" />
                                            {t('create.add')}
                                        </Badge>
                                    )
                            }
                        </div>
                    ))
                }
            </div>
        </>
    )
}
