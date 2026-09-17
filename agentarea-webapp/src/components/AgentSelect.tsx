"use client";

import { AgentIdentity } from "@/components/AgentIdentity";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EntityIcon } from "@/lib/entity-icons";

export interface SelectableAgent {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  color_token?: string | null;
}

/** Pick one agent from a dropdown.
 *
 * Three screens spelled this out separately and each showed the agent
 * differently — bare name, name plus description, or an identity chip. They all
 * render the chip now, so an agent looks the same wherever it is chosen.
 */
export function AgentSelect({
  agents,
  value,
  onChange,
  placeholder,
  id,
  name,
  ariaLabel,
  className,
  disabled,
}: {
  agents: SelectableAgent[];
  value: string;
  onChange: (agentId: string) => void;
  placeholder: string;
  id?: string;
  /** Set when the value has to reach a server action through the form post. */
  name?: string;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <Select name={name} value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        id={id}
        aria-label={ariaLabel}
        className={className ?? "h-9 gap-2 [&>span]:flex-1 [&>span]:text-left"}
      >
        <EntityIcon kind="agent" className="h-4 w-4 shrink-0 text-primary" />
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id} textValue={agent.name}>
            <AgentIdentity agent={agent} size="xs" />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
