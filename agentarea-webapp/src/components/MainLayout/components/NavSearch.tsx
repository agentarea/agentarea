"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Search } from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { SidebarMenuButton, useSidebar } from "@/components/ui/sidebar";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { navItemClassName, type NavMain } from "./NavMain";

type Sections = React.ComponentProps<typeof NavMain>["sections"];

/** The sidebar's search: a ⌘K palette over the pages the sidebar links to. */
export function NavSearch({ sections }: { sections: Sections }) {
  const t = useTranslations("Sidebar");
  const router = useWorkspaceRouter();
  const { open: sidebarOpen } = useSidebar();
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (url: string) => {
    setOpen(false);
    router.push(url);
  };

  return (
    <>
      {sidebarOpen ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex h-8 w-full items-center gap-2 rounded-md border border-sidebar-border bg-background px-2 text-[13px] text-muted-foreground shadow-sm transition-colors hover:border-zinc-300 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring dark:hover:border-zinc-600"
        >
          <Search className="size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate text-left">
            {t("searchPlaceholder")}
          </span>
          <Kbd keys={["⌘", "K"]} />
        </button>
      ) : (
        <SidebarMenuButton
          tooltip={{
            children: (
              <span className="flex items-center gap-1.5">
                {t("search")}
                <Kbd keys={["⌘", "K"]} variant="inverse" />
              </span>
            ),
          }}
          aria-label={t("search")}
          onClick={() => setOpen(true)}
          className={navItemClassName}
        >
          <Search />
        </SidebarMenuButton>
      )}
      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder={t("searchPlaceholder")} />
        <CommandList>
          <CommandEmpty>{t("searchEmpty")}</CommandEmpty>
          {sections.map((section, index) => {
            const label = section.labelKey
              ? t(section.labelKey)
              : section.label;
            return (
              <CommandGroup
                key={section.labelKey ?? section.label ?? index}
                heading={label}
              >
                {section.items.flatMap((item) =>
                  [item, ...(item.items ?? [])].map((entry) => {
                    const title = entry.titleKey
                      ? t(entry.titleKey)
                      : entry.title;
                    const Icon = item.icon;
                    return (
                      <CommandItem
                        key={entry.url}
                        value={`${title} ${entry.url}`}
                        onSelect={() => go(entry.url)}
                      >
                        {Icon && <Icon className="mr-2 size-4" />}
                        {title}
                      </CommandItem>
                    );
                  })
                )}
              </CommandGroup>
            );
          })}
        </CommandList>
      </CommandDialog>
    </>
  );
}
