"use client";

import { useState, type ComponentType, type SVGProps } from "react";
import { useTranslations } from "next-intl";
import { UiNodeGroupEnum, type UiNode } from "@ory/client-fetch";
import { KeyRound } from "lucide-react";
import { useFormContext } from "react-hook-form";
import { GitHubIcon, GoogleIcon } from "@/components/brand-icons";
import { Button } from "@/components/ui/button";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { deterministicHue } from "@/lib/avatar-hue";
import { socialProviders } from "./oryNodes";
import SettingsRow from "./SettingsRow";
import { SettingsSection } from "./SettingsSection";

/** Brand name and mark of the providers configured in kratos.yml. */
const BRANDS: Record<
  string,
  { name: string; Logo: ComponentType<SVGProps<SVGSVGElement>> }
> = {
  github: { name: "GitHub", Logo: GitHubIcon },
  google: { name: "Google", Logo: GoogleIcon },
};

export default function ConnectedAccountsSection({
  nodes,
}: {
  nodes: UiNode[];
}) {
  const t = useTranslations("SettingsPage.accounts");
  const {
    setValue,
    formState: { isSubmitting },
  } = useFormContext();
  const [pending, setPending] = useState<string | null>(null);

  // Linking leaves for the provider's consent page; unlinking answers in place.
  const submit = (action: "link" | "unlink", id: string) => {
    setValue(action === "link" ? "unlink" : "link", "");
    setValue(action, id);
    setValue("method", UiNodeGroupEnum.Oidc);
    setPending(id);
  };

  return (
    <SettingsSection title={t("title")} description={t("description")}>
      {socialProviders(nodes).map(({ id, label, connected }) => {
        const brand = BRANDS[id];
        const action = connected ? "unlink" : "link";
        const busy = isSubmitting && pending === id;
        return (
          <SettingsRow
            key={id}
            tile={
              <EntityAvatar
                size={32}
                hue={deterministicHue(id)}
                iconScale={brand ? 0.56 : 0.5}
                icon={
                  brand ? (
                    <brand.Logo className="text-foreground" />
                  ) : (
                    <KeyRound strokeWidth={1.85} />
                  )
                }
                aria-hidden
              />
            }
            title={brand?.name ?? label}
            description={connected ? undefined : t("notConnected")}
          >
            {connected && (
              <StatusIndicator kind="active" size="sm">
                {t("connected")}
              </StatusIndicator>
            )}
            <Button
              type="submit"
              variant={connected ? "ghost" : "outline"}
              size="sm"
              name={action}
              value={id}
              disabled={isSubmitting && !busy}
              isLoading={busy}
              onClick={() => submit(action, id)}
            >
              {t(connected ? "disconnect" : "connect")}
            </Button>
          </SettingsRow>
        );
      })}
    </SettingsSection>
  );
}
