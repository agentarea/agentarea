import { useTranslations } from "next-intl";
import {
  CalendarClock,
  FolderKanban,
  Plus,
  Puzzle,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Option = { id: string; name: string };

interface ComposerMenuProps {
  onOpenResources?: () => void;
  onSchedule?: () => void;
  projects?: Option[];
  currentProjectId?: string | null;
  onProjectChange?: (projectId: string | null) => void;
  policies?: Option[];
  currentPolicyId?: string | null;
  onPolicyChange?: (policyId: string | null) => void;
  disabled?: boolean;
}

const NONE = "__none__";

/**
 * Everything a task may carry besides who takes it and its files: extra MCPs
 * and skills, a project, a policy, a later start. What is set shows beside it as a
 * chip; what is left at its default stays in here.
 */
export function ComposerMenu({
  onOpenResources,
  onSchedule,
  projects,
  currentProjectId,
  onProjectChange,
  policies,
  currentPolicyId,
  onPolicyChange,
  disabled,
}: ComposerMenuProps) {
  const t = useTranslations("Chat.inputControls");
  const itemClass = "gap-2 text-[13px]";
  const iconClass = "h-3.5 w-3.5 text-zinc-500";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          disabled={disabled}
          aria-label={t("add")}
          className="h-7 w-7 shrink-0 rounded-md p-0 text-zinc-500 hover:bg-muted hover:text-zinc-700 data-[state=open]:bg-muted dark:text-zinc-400 dark:hover:text-zinc-200"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={8}
        className="w-56"
        // An item opens a picker of its own; focus going back to this button
        // would count as a click outside it and close it at once.
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        {onOpenResources ? (
          <DropdownMenuItem className={itemClass} onSelect={onOpenResources}>
            <Puzzle className={iconClass} />
            {t("mcpsAndSkills")}
          </DropdownMenuItem>
        ) : null}
        {projects?.length && onProjectChange ? (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className={itemClass}>
              <FolderKanban className={iconClass} />
              {t("project")}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-80 w-56 overflow-y-auto">
              <DropdownMenuRadioGroup
                value={currentProjectId ?? NONE}
                onValueChange={(id) => onProjectChange(id === NONE ? null : id)}
              >
                <DropdownMenuRadioItem className={itemClass} value={NONE}>
                  {t("noProject")}
                </DropdownMenuRadioItem>
                {projects.map((project) => (
                  <DropdownMenuRadioItem
                    key={project.id}
                    className={itemClass}
                    value={project.id}
                  >
                    <span className="truncate">{project.name}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ) : null}
        {policies?.length && onPolicyChange ? (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className={itemClass}>
              <ShieldCheck className={iconClass} />
              {t("taskPolicy")}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-80 w-64 overflow-y-auto">
              <DropdownMenuRadioGroup
                value={currentPolicyId ?? NONE}
                onValueChange={(id) => onPolicyChange(id === NONE ? null : id)}
              >
                <DropdownMenuRadioItem className={itemClass} value={NONE}>
                  {t("defaultPolicy")}
                </DropdownMenuRadioItem>
                {policies.map((policy) => (
                  <DropdownMenuRadioItem
                    key={policy.id}
                    className={itemClass}
                    value={policy.id}
                  >
                    <span className="truncate">{policy.name}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ) : null}
        {onSchedule ? (
          <DropdownMenuItem className={itemClass} onSelect={onSchedule}>
            <CalendarClock className={iconClass} />
            {t("runLater")}
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
