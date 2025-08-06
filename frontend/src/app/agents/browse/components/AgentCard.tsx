import { Agent } from "@/types";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { StatusBadge } from "@/components/ui/status-badge";

type AgentCardProps = {
  agent: Agent;
}

export default function AgentCard({ agent }: AgentCardProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 justify-between">
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
                        {agent.model_id}
                </div>
            </div>
        </div>
        <StatusBadge status={agent.status} variant="agent" />
        </div>
        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
            {agent.description}
        </p>
        {/* FIX DATA for avatar urls */}
        <AvatarCircles
            className="mt-2"
            maxDisplay={4}
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
    </div>
  );
}
