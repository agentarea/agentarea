"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CreditCard,
  SlidersHorizontal,
  Key,
  ScrollText,
  User,
} from "lucide-react";
import {
  SettingsSidebarView,
  type SettingsNavSection,
} from "@agentarea/ui-shell";
import { NavUser } from "@/components/MainLayout/components/NavUser";
import { useBillingUrl } from "@/lib/use-billing-url";

/**
 * The platform's settings sidebar: the shared view, wired to this app's translations,
 * router and session.
 *
 * Everything platform-specific lives here so the view itself stays renderable by a
 * deployment that has none of it. Callers are unchanged — ConditionalLayout still
 * renders <SettingsSidebarContent /> with no props.
 */
export function SettingsSidebarContent() {
  const pathname = usePathname();
  const t = useTranslations("SettingsSidebar");
  // Empty on any deployment that does not sell, which is the open default.
  const billingUrl = useBillingUrl();

  const sections: SettingsNavSection[] = [
    {
      label: t("account"),
      items: [
        { title: t("profile"), href: "/settings", icon: User },
        ...(billingUrl
          ? [{ title: t("billing"), href: billingUrl, icon: CreditCard }]
          : []),
      ],
    },
    {
      label: t("workspace"),
      items: [
        { title: t("apiKeys"), href: "/admin/api-keys", icon: Key },
        {
          title: t("workspaceSettings"),
          href: "/admin/workspace",
          icon: SlidersHorizontal,
        },
        { title: t("auditLog"), href: "/settings/audit", icon: ScrollText },
      ],
    },
  ];

  return (
    <SettingsSidebarView
      title={t("title")}
      backToApp={t("backToApp")}
      backHref="/workplace"
      sections={sections}
      currentPath={pathname}
      footer={<NavUser />}
      linkComponent={Link}
    />
  );
}
