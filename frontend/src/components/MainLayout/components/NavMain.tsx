"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Circle, type LucideIcon } from "lucide-react";
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
                        className="ring-0 transition-none focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                        onMouseEnter={() => openOnHover(item.url)}
                        onMouseLeave={() => closeOnHoverLeave(item.url)}
                      >
                        {item.icon && <item.icon />}
                        {state === "collapsed" ? null : (
                          <span>
                            {item.titleKey ? t(item.titleKey) : item.title}
                          </span>
                        )}
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
                open={isCollapsibleOpen(item.url)}
                className="group/collapsible"
                onOpenChange={(open: boolean) => {
                  if (open) {
                    setOpenCollapsibles(
                      (prev: Set<string>) => new Set([...prev, item.url])
                    );
                  } else {
                    setOpenCollapsibles((prev: Set<string>) => {
                      const next = new Set(prev);
                      next.delete(item.url);
                      return next;
                    });
                  }
                }}
              >
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton>
                      {item.icon && <item.icon />}
                      <span>
                        {item.titleKey ? t(item.titleKey) : item.title}
                      </span>
                      <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {item.items?.map((subItem) => (
                        <SidebarMenuSubItem key={subItem.title}>
                          <SidebarMenuSubButton
                            asChild
                            isActive={isItemActive(subItem.url)}
                          >
                            <Link href={subItem.url}>
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
