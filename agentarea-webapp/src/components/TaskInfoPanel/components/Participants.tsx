import { useTranslations } from "next-intl";
import { GitFork, User } from "lucide-react";
import { AgentLink } from "@/components/AgentIdentity";
import Section from "./Section";

interface ParticipantsProps {
  agentId: string;
  agentName?: string | null;
  delegatedAgents?: string[];
}

interface Participant {
  name: string;
  role: string;
  icon: typeof User;
  iconClass: string;
}

function ParticipantRow({ participant }: { participant: Participant }) {
  const Icon = participant.icon;

  return (
    <div className="flex items-center gap-2 px-0.5 py-1">
      <Icon className={`h-4 w-4 shrink-0 ${participant.iconClass}`} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12px] font-medium text-foreground">
          {participant.name}
        </div>
        <div className="truncate text-[10px] text-muted-foreground">
          {participant.role}
        </div>
      </div>
    </div>
  );
}

export default function Participants({
  agentId,
  agentName,
  delegatedAgents,
}: ParticipantsProps) {
  const t = useTranslations("TaskInfoPanel");

  const requester: Participant = {
    name: t("you"),
    role: t("roleRequester"),
    icon: User,
    iconClass: "text-zinc-500",
  };
  const delegated: Participant[] = (delegatedAgents || []).map((name) => ({
    name,
    role: t("roleDelegated"),
    icon: GitFork,
    iconClass: "text-sky-600 dark:text-sky-400",
  }));

  return (
    <Section title={t("participants")} contentClassName="space-y-1.5 text-xs">
      <ParticipantRow participant={requester} />
      <AgentLink
        agent={{ id: agentId, name: agentName || t("agent") }}
        size="xs"
        meta={t("rolePrimaryAgent")}
        className="w-full px-0.5 py-1"
        nameClassName="text-[12px]"
        metaClassName="text-[10px]"
      />
      {delegated.map((participant, index) => (
        <ParticipantRow
          key={`${participant.name}-${index}`}
          participant={participant}
        />
      ))}
    </Section>
  );
}
