"use client";

import { useTranslations } from "next-intl";
import { EFFECT_STYLES } from "@/app/w/[workspace]/(main)/policies/components/policy-effects";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  TOOL_POLICIES,
  type ToolPolicy,
  type ToolPolicyState,
} from "../../tool-policy";

function PolicyLabel({ policy }: { policy: ToolPolicy }) {
  const tEffects = useTranslations("PoliciesPage.editor.effects");
  const Icon = EFFECT_STYLES[policy].icon;
  return (
    <span className="flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      {tEffects(policy)}
    </span>
  );
}

/**
 * What the engine does with the tool when another rule makes it stricter than
 * the default set here; hovering gives the engine's reason.
 */
function StricterVerdict({ state }: { state: ToolPolicyState }) {
  const t = useTranslations("MCPServersPage.instanceDetail.tools.policy");
  const tEffects = useTranslations("PoliciesPage.editor.effects");
  if (state.effective === state.default) return null;
  const Icon = EFFECT_STYLES[state.effective].icon;
  const text = (
    <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
      <Icon className="h-3 w-3" />
      {t("stricter", { effect: tEffects(state.effective) })}
    </span>
  );
  if (!state.reason) return text;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-default">{text}</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-[280px]">
          {state.reason}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * A workspace default policy: allow, approval, or deny. `null` is a set of
 * tools that do not share one, shown as mixed until one is picked. Without
 * `onChange` it is read-only: the viewer may see the policy but not set it.
 */
export function ToolPolicySelect({
  value,
  onChange,
  label,
  prefix,
  effective,
}: {
  value: ToolPolicy | null;
  onChange?: (policy: ToolPolicy) => void;
  label: string;
  /** Leads the chosen value on the trigger, e.g. "All:" for a bulk control. */
  prefix?: string;
  /** The engine's verdict, shown under the control when other rules tighten it. */
  effective?: ToolPolicyState;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.tools.policy");

  const verdict = effective && <StricterVerdict state={effective} />;

  if (!onChange) {
    return value ? (
      <div>
        <span className="text-xs text-foreground/80" aria-label={label}>
          <PolicyLabel policy={value} />
        </span>
        {verdict}
      </div>
    ) : null;
  }

  return (
    <div>
      <Select
        value={value ?? ""}
        onValueChange={(v) => onChange(v as ToolPolicy)}
      >
        <SelectTrigger
          className="h-7 w-full text-xs text-foreground"
          aria-label={label}
        >
          <SelectValue
            placeholder={prefix ? `${prefix} ${t("mixed")}` : t("mixed")}
          >
            {value && (
              <span className="flex items-center gap-1">
                {prefix && (
                  <span className="text-muted-foreground max-md:hidden">
                    {prefix}
                  </span>
                )}
                <PolicyLabel policy={value} />
              </span>
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {TOOL_POLICIES.map((policy) => (
            <SelectItem key={policy} value={policy}>
              <PolicyLabel policy={policy} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {verdict}
    </div>
  );
}
