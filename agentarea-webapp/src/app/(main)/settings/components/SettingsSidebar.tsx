"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  CreditCard,
  Download,
  Key,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

const settingsNav = [
  {
    label: "Account",
    items: [
      { title: "Profile", href: "/settings", icon: User },
      { title: "Billing", href: "/settings/billing", icon: CreditCard },
    ],
  },
  {
    label: "Workspace",
    items: [
      { title: "API Keys", href: "/admin/api-keys", icon: Key },
      { title: "Import / Export", href: "/admin/workspace", icon: Download },
    ],
  },
];

export default function SettingsSidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/settings"
      ? pathname === "/settings"
      : pathname.startsWith(href);

  return (
    <aside className="w-56 shrink-0 border-r border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/50 overflow-y-auto">
      <div className="p-4">
        <Link
          href="/workplace"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>

        <nav className="space-y-6">
          {settingsNav.map((section) => (
            <div key={section.label}>
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-2 px-2">
                {section.label}
              </h4>
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href as any}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                        isActive(item.href)
                          ? "bg-zinc-200/70 dark:bg-zinc-800 text-foreground font-medium"
                          : "text-muted-foreground hover:text-foreground hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                      )}
                    >
                      <item.icon className="h-4 w-4" />
                      {item.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </div>
    </aside>
  );
}
