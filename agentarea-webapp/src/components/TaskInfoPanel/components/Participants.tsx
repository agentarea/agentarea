import { useTranslations } from "next-intl";
import { Bot, GitFork, User } from "lucide-react";
import Section from "./Section";

interface ParticipantsProps {
  agentName?: string | null;
  delegatedAgents?: string[];
}

interface Participant {
  name: string;
  role: string;
  icon: typeof User;
  iconClass: string;
}

export default function Participants({ agentName, delegatedAgents }: ParticipantsProps) {
  const t = useTranslations("TaskInfoPanel");

  const participants: Participant[] = [
    { name: t("you"), role: t("roleRequester"), icon: User, iconClass: "text-zinc-500" },
    {
      name: agentName || t("agent"),
      role: t("rolePrimaryAgent"),
      icon: Bot,
      iconClass: "text-primary",
    },
    ...(delegatedAgents || []).map((name) => ({
      name,
      role: t("roleDelegated"),
      icon: GitFork,
      iconClass: "text-violet-600 dark:text-violet-400",
    })),
  ];

  return (
    <Section title={t("participants")} contentClassName="space-y-1.5 text-xs">
      {participants.map((p, i) => {
        const Icon = p.icon;
        return (
          <div
            key={`${p.name}-${i}`}
            className="flex items-center gap-2 px-0.5 py-1"
          >
            <Icon className={`h-4 w-4 shrink-0 ${p.iconClass}`} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-medium text-foreground">{p.name}</div>
              <div className="truncate text-[10px] text-muted-foreground">{p.role}</div>
            </div>
          </div>
        );
      })}
    </Section>
  );
}
