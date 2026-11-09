
import { useTranslations } from "next-intl";
import { Cpu } from "lucide-react";
import { HarnessIcon, harnessOf } from "@/components/harnesses";
import { ProviderIcon } from "@/components/ui/provider-icon";
import type { RunTarget } from "@/lib/run-targets";
import { ContextSelect } from "./ContextSelect";

interface RunTargetSelectProps {
  targets: RunTarget[];
  value: string;
  disabled?: boolean;
  onValueChange: (value: string) => void;
}

/** Where the run goes and on which model: the platform, or a Codex / Claude Code client's runner. */
export function RunTargetSelect({
  targets,
  value,
  disabled,
  onValueChange,
}: RunTargetSelectProps) {
  const t = useTranslations("Chat.inputControls");
  const options = targets.map((target) =>
    target.on === "platform"
      ? {
          id: target.id,
          name: target.name,
          description: [target.provider, t("onPlatform")]
            .filter(Boolean)
            .join(" · "),
        }
      : {
          id: target.id,
          name: `${target.name} · ${target.model ?? t("cliDefaultModel")}`,
          description: [
            harnessOf(target.kind).label,
            target.online ? null : t("runnerOffline"),
          ]
            .filter(Boolean)
            .join(" · "),
        }
  );
  const icon = (id: string, className: string) => {
    const target = targets.find((candidate) => candidate.id === id);
    if (!target) return null;
    return target.on === "platform" ? (
      <ProviderIcon
        iconUrl={target.iconUrl}
        name={target.provider ?? target.name}
        size="sm"
        className={className}
      />
    ) : (
      <HarnessIcon kind={target.kind} className={className} />
    );
  };

  return (
    <ContextSelect
      className="shrink min-w-0"
      icon={Cpu}
      label={t("runsOn")}
      value={value}
      disabled={disabled}
      onValueChange={onValueChange}
      options={options}
      renderTriggerIcon={(option) => icon(option.id, "h-3.5 w-3.5 shrink-0")}
      renderOptionIcon={(option) =>
        icon(option.id, "mt-0.5 h-3.5 w-3.5 shrink-0")
      }
    />
  );
}
