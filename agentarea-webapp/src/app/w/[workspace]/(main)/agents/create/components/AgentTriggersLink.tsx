import Link from "@/components/WorkspaceLink";
import { useTranslations } from "next-intl";
import { Zap } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";

/** An existing agent's triggers are edited on the Triggers pages, not here. */
export default function AgentTriggersLink({ href }: { href: string }) {
  const t = useTranslations("AgentsPage.create");

  return (
    <div className="space-y-2">
      <FormLabel icon={Zap}>{t("agentTriggers")}</FormLabel>
      <p className="text-xs text-muted-foreground">
        {t("triggersManagedElsewhere")}{" "}
        <Link href={href} className="text-primary hover:underline">
          {t("openTriggers")}
        </Link>
      </p>
    </div>
  );
}
