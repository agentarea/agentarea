import { Agent } from "@/types";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { StatusBadge } from "@/components/ui/status-badge";
import { listModelInstances } from "@/lib/api";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

type AgentCardProps = {
  agent: Agent;
}

interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
}

export default function AgentCard({ agent }: AgentCardProps) {
    console.log(agent);
    const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        const fetchModelInfo = async () => {
            if (!agent.model_id) return;
            
            try {
                setIsLoading(true);
                
                const { data, error } = await listModelInstances();
                if (error) {
                    console.error('Failed to fetch model instances:', error);
                    return;
                }
                
                // Find the model in the response
                const modelInstance = data?.find(
                    (instance: any) => instance.id === agent.model_id
                );
                
                if (modelInstance) {
                    setModelInfo({
                        provider_name: modelInstance.provider_name || undefined,
                        model_display_name: modelInstance.model_display_name || undefined,
                        config_name: modelInstance.config_name || undefined
                    });
                } else {
                    console.log('Model not found:', agent.model_id);
                }
            } catch (err) {
                console.error('Failed to fetch model info:', err);
            } finally {
                setIsLoading(false);
            }
        };

        fetchModelInfo();
    }, [agent.model_id]);

    const getModelDisplayText = () => {
        if (isLoading) return null;
        if (!modelInfo) return null;
        
        const parts = [];
        if (modelInfo.provider_name) parts.push(modelInfo.provider_name);
        if (modelInfo.model_display_name) parts.push(modelInfo.model_display_name);
        if (modelInfo.config_name) parts.push(`(${modelInfo.config_name})`);
        
        return parts.length > 0 ? parts.join(" - ") : null;
    };

    const modelDisplayText = getModelDisplayText();

    return (
        <div className="flex flex-col justify-between gap-6 h-full">
            <div className="flex flex-col gap-2 px-[16px] md:px-[20px] lg:px-[24px]">
                <div className="flex items-start gap-3 justify-between">
                    <div className="flex items-center gap-3">
                        {agent.icon && (
                            <img 
                                src={agent.icon} 
                                alt={`${agent.name} icon`} 
                                className="w-8 h-8 rounded dark:invert"
                            />
                        )}
                        <div className="flex flex-col">
                            <h3>
                                {agent.name}
                            </h3>
                                <div className="note">
                                    <span>{modelInfo?.config_name || modelInfo?.provider_name}</span>
                                    {
                                        modelInfo?.model_display_name && (
                                            <span className="pl-1 font-semibold">({modelInfo?.model_display_name})</span>
                                        )
                                    }
                                </div>
                        </div>
                    </div>
                    <StatusBadge status={agent.status} variant="agent" />
                </div>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                    {agent.description || agent.instruction}
                </p>
            </div>

            <div className="
                px-[16px] md:px-[20px] lg:px-[24px] 
                py-[10px]
                group-hover:bg-zinc-100/70 dark:group-hover:bg-zinc-700/80
                transition-colors duration-300
                border-t border-zinc-200 dark:border-zinc-700
                flex items-center justify-between
"
            >
                {/* FIX DATA for avatar urls */}
                <AvatarCircles
                    maxDisplay={5}
                    avatarUrls={[
                        {
                            imageUrl: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ2sSeQqjaUTuZ3gRgkKjidpaipF_l6s72lBw&s",
                        },
                        {
                            imageUrl: "https://cdn.worldvectorlogo.com/logos/jira-1.svg",
                        },
                        {
                            imageUrl: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiiqczgVWrWg2wpS5wC5iW2u3ppLqauc10yw&s",
                        },{
                            imageUrl: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/2048px-Notion-logo.svg.png",
                        },
                        {
                            imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
                        },
                        {
                            imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
                        },
                        {
                            imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
                        }
                    ]}
                />
                <div className="small-link text-muted-foreground/70 group-hover:text-primary">
                    View agent
                    <ArrowRight className="h-4 w-4" />
                </div>
            </div>
        </div>
    );
}
