"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Circle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar";

export function NavMain({
  items,
}: {
  items: {
    title: string;
    titleKey?: string;
    url: string;
    icon?: LucideIcon;
    isActive?: boolean;
    items?: {
      title: string;
      titleKey?: string;
      url: string;
    }[];
  }[];
}) {
  const pathname = usePathname();
  const [openCollapsibles, setOpenCollapsibles] = useState<Set<string>>(
    new Set()
  );
  const [hoveredDropdownId, setHoveredDropdownId] = useState<string | null>(
    null
  );
  const hoverCloseTimeoutRef = useRef<number | null>(null);
  const openOnHover = (id: string) => {
    if (hoverCloseTimeoutRef.current) {
      window.clearTimeout(hoverCloseTimeoutRef.current);
      hoverCloseTimeoutRef.current = null;
    }
    setHoveredDropdownId(id);
  };
  const closeOnHoverLeave = (id: string) => {
    hoverCloseTimeoutRef.current = window.setTimeout(() => {
      setHoveredDropdownId((prev) => (prev === id ? null : prev));
    }, 220);
  };
  const closeDropdownImmediately = () => {
    if (hoverCloseTimeoutRef.current) {
      window.clearTimeout(hoverCloseTimeoutRef.current);
      hoverCloseTimeoutRef.current = null;
    }
    setHoveredDropdownId(null);
  };
  const t = useTranslations("Sidebar");
  // cleanup hover close timeout on unmount
  useEffect(() => {
    return () => {
      if (hoverCloseTimeoutRef.current) {
        window.clearTimeout(hoverCloseTimeoutRef.current);
      }
    };
  }, []);
  // Восстанавливаем только открытые коллапсы из localStorage при инициализации
  useEffect(() => {
    const savedOpenCollapsibles = localStorage.getItem("navOpenCollapsibles");
    if (savedOpenCollapsibles) {
      try {
        const parsed: string[] = JSON.parse(savedOpenCollapsibles);
        setOpenCollapsibles(new Set(parsed));
      } catch (e) {
        console.warn("Failed to parse saved open collapsibles:", e);
      }
    }
  }, []);

  // Открываем соответствующий коллапс при изменении pathname (если активный пункт внутри него)
  useEffect(() => {
    // Если активный пункт верхнего уровня и он сам является коллапсом
    const currentActiveItem = items.find((item) => item.url === pathname);
    if (currentActiveItem?.items) {
      setOpenCollapsibles((prev: Set<string>) => {
        const next = new Set(prev);
        next.add(currentActiveItem.url);
        return next;
      });
      return;
    }

    // Иначе ищем родителя для активного подпункта
    const parentWithActiveSub = items.find((item) =>
      item.items?.some((sub) => sub.url === pathname)
    );
    if (parentWithActiveSub) {
      setOpenCollapsibles((prev: Set<string>) => {
        const next = new Set(prev);
        next.add(parentWithActiveSub.url);
        return next;
      });
    }
  }, [pathname, items]);

  // Сохраняем открытые коллапсы в localStorage при изменении
  useEffect(() => {
    localStorage.setItem(
      "navOpenCollapsibles",
      JSON.stringify(Array.from(openCollapsibles))
    );
  }, [openCollapsibles]);

  // Активность ссылки для точного совпадения и вложенных путей
  const isItemActive = (url: string) =>
    pathname === url || pathname.startsWith(`${url}/`);

  // Проверяем, открыт ли коллапс
  const isCollapsibleOpen = (id: string) => openCollapsibles.has(id);

  const { state, isMobile } = useSidebar();

  return (
    <SidebarGroup>
      {/* <SidebarGroupLabel>Platform</SidebarGroupLabel> */}
      <SidebarMenu>
        {items.map((item) => {
          if (item.items) {
            // When collapsed, show a popout dropdown like TeamSwitcher/NavUser
            if (state === "collapsed" && !isMobile) {
              const isHovered = hoveredDropdownId === item.url;
              return (
                <SidebarMenuItem key={item.title}>
                  <DropdownMenu open={isHovered} modal={false}>
                    <DropdownMenuTrigger asChild>
                      <SidebarMenuButton
                        className="group/btn relative overflow-hidden transition-all duration-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 data-[state=open]:bg-zinc-100 dark:data-[state=open]:bg-zinc-800"
                        onMouseEnter={() => openOnHover(item.url)}
                        onMouseLeave={() => closeOnHoverLeave(item.url)}
                      >
                        {item.icon && <item.icon className="transition-colors group-hover/btn:text-primary" />}
                        {state === "collapsed" ? null : (
                          <span className="font-medium">
                            {item.titleKey ? t(item.titleKey) : item.title}
                          </span>
                        )}
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-0 bg-primary transition-all duration-300 group-hover/btn:h-6 rounded-r-full" />
                      </SidebarMenuButton>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="start"
                      side="right"
                      sideOffset={0}
                      className="animate-none data-[state=closed]:animate-none data-[state=open]:animate-none"
                      onMouseEnter={() => openOnHover(item.url)}
                      onMouseLeave={() => closeOnHoverLeave(item.url)}
                      onCloseAutoFocus={(e) => e.preventDefault()}
                    >
                      <DropdownMenuLabel className="text-xs text-muted-foreground">
                        {item.titleKey ? t(item.titleKey) : item.title}
                      </DropdownMenuLabel>
                      {item.items?.map((subItem) => (
                        <DropdownMenuItem
                          key={subItem.title}
                          className="cursor-pointer gap-2 p-2"
                          onSelect={closeDropdownImmediately}
                          asChild
                        >
                          <Link
                            href={subItem.url}
                            onClick={closeDropdownImmediately}
                            className="flex cursor-pointer items-center gap-2"
                          >
                            <ChevronRight className="size-3.5 shrink-0" />
                            {subItem.titleKey
                              ? t(subItem.titleKey)
                              : subItem.title}
                          </Link>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </SidebarMenuItem>
              );
            }
            // Expanded: keep collapsible behavior
            return (
              <Collapsible
                key={item.title}
                asChild
                defaultOpen={isCollapsibleOpen(item.url)}
                open={isCollapsibleOpen(item.url)}
                onOpenChange={(open) => {
                  setOpenCollapsibles((prev) => {
                    const next = new Set(prev);
                    if (open) {
                      next.add(item.url);
                    } else {
                      next.delete(item.url);
                    }
                    return next;
                  });
                }}
                className="group/collapsible"
              >
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      tooltip={item.titleKey ? t(item.titleKey) : item.title}
                      className={cn(
                        "group/btn relative overflow-hidden transition-all duration-200",
                        isItemActive(item.url) 
                          ? "bg-zinc-100 dark:bg-zinc-800 font-medium text-primary" 
                          : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                      )}
                    >
                      {item.icon && <item.icon className={cn("transition-colors duration-200", isItemActive(item.url) ? "text-primary" : "text-zinc-500 group-hover/btn:text-zinc-900 dark:text-zinc-400 dark:group-hover/btn:text-zinc-100")} />}
                      <span className={cn("transition-colors", isItemActive(item.url) ? "text-primary" : "")}>
                        {item.titleKey ? t(item.titleKey) : item.title}
                      </span>
                      
                      {/* Active indicator strip */}
                      {isItemActive(item.url) && (
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-primary rounded-r-full" />
                      )}
                      
                      <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90 text-zinc-400 group-hover/btn:text-zinc-600 dark:group-hover/btn:text-zinc-300" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {item.items?.map((subItem) => (
                        <SidebarMenuSubItem key={subItem.title}>
                          <SidebarMenuSubButton
                            asChild
                            isActive={isItemActive(subItem.url)}
                            className={cn(
                              "transition-all duration-200 relative overflow-hidden",
                              isItemActive(subItem.url) 
                                ? "bg-primary/5 text-primary font-medium"
                                : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                            )}
                          >
                            <Link href={subItem.url}>
                              {/* Dot indicator removed as requested */}
                              <span>
                                {subItem.titleKey
                                  ? t(subItem.titleKey)
                                  : subItem.title}
                              </span>
                            </Link>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>
            );
          }
          return (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                asChild
                isActive={isItemActive(item.url)}
                tooltip={item.titleKey ? t(item.titleKey) : item.title}
              >
                <Link href={item.url}>
                  {item.icon && <item.icon />}
                  <span>{item.titleKey ? t(item.titleKey) : item.title}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
