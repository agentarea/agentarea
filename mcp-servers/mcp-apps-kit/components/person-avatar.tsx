import { Bot, UserRound } from "lucide-react";
import { initials } from "../lib/format";
import { cn } from "../lib/utils";
import { Avatar, AvatarFallback } from "../ui/avatar";

export type Person = { name: string; kind: "human" | "agent" };

/** People are round with initials; agents are rounded squares with a bot glyph, so the two never read alike. */
export function PersonAvatar({ person, className }: { person: Person | null; className?: string }) {
  if (!person) {
    return (
      <Avatar className={cn("border-subtle-foreground/60 size-5 border border-dashed", className)} title="Unassigned">
        <AvatarFallback className="text-subtle-foreground bg-transparent">
          <UserRound className="size-3" />
        </AvatarFallback>
      </Avatar>
    );
  }
  if (person.kind === "agent") {
    return (
      <Avatar className={cn("size-5 rounded-[5px]", className)} title={`${person.name} (agent)`}>
        <AvatarFallback className="text-agent rounded-[5px] bg-[color-mix(in_oklab,var(--agent)_16%,transparent)]">
          <Bot className="size-[70%]" strokeWidth={2.25} />
        </AvatarFallback>
      </Avatar>
    );
  }
  return (
    <Avatar className={cn("size-5", className)} title={person.name}>
      <AvatarFallback className="bg-secondary text-foreground text-[9px] font-semibold">
        {initials(person.name)}
      </AvatarFallback>
    </Avatar>
  );
}

/** "Agent" next to an agent's name. */
export function AgentTag() {
  return <span className="text-agent shrink-0 text-[10px] font-semibold tracking-wide uppercase">Agent</span>;
}

/** Avatar plus name, with an "Agent" tag for agents. */
export function PersonName({
  person,
  className,
  empty = "Unassigned",
}: {
  person: Person | null;
  className?: string;
  empty?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      <PersonAvatar person={person} className="size-4" />
      <span className="truncate">{person ? person.name : empty}</span>
      {person?.kind === "agent" && <AgentTag />}
    </span>
  );
}
