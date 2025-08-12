"use client"

import { ChevronRight, type LucideIcon } from "lucide-react"
import { usePathname } from "next/navigation"
import Link from "next/link"
import { useState, useEffect } from "react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from '@/components/ui/sidebar'

export function NavMain({
  items,
}: {
  items: {
    title: string
    url: string
    icon?: LucideIcon
    isActive?: boolean
    items?: {
      title: string
      url: string
    }[]
  }[]
}) {
  const pathname = usePathname()
  const [openCollapsibles, setOpenCollapsibles] = useState<Set<string>>(new Set())

  // Восстанавливаем только открытые коллапсы из localStorage при инициализации
  useEffect(() => {
    const savedOpenCollapsibles = localStorage.getItem('navOpenCollapsibles')
    if (savedOpenCollapsibles) {
      try {
        const parsed: string[] = JSON.parse(savedOpenCollapsibles)
        setOpenCollapsibles(new Set(parsed))
      } catch (e) {
        console.warn('Failed to parse saved open collapsibles:', e)
      }
    }
  }, [])

  // Открываем соответствующий коллапс при изменении pathname (если активный пункт внутри него)
  useEffect(() => {
    // Если активный пункт верхнего уровня и он сам является коллапсом
    const currentActiveItem = items.find(item => item.url === pathname)
    if (currentActiveItem?.items) {
      setOpenCollapsibles((prev: Set<string>) => {
        const next = new Set(prev)
        next.add(currentActiveItem.url)
        return next
      })
      return
    }

    // Иначе ищем родителя для активного подпункта
    const parentWithActiveSub = items.find(item => item.items?.some(sub => sub.url === pathname))
    if (parentWithActiveSub) {
      setOpenCollapsibles((prev: Set<string>) => {
        const next = new Set(prev)
        next.add(parentWithActiveSub.url)
        return next
      })
    }
  }, [pathname, items])

  // Сохраняем открытые коллапсы в localStorage при изменении
  useEffect(() => {
    localStorage.setItem('navOpenCollapsibles', JSON.stringify(Array.from(openCollapsibles)))
  }, [openCollapsibles])

  // Активность обычных ссылок — только по текущему URL
  const isItemActive = (url: string) => pathname === url

  // Проверяем, открыт ли коллапс
  const isCollapsibleOpen = (id: string) => openCollapsibles.has(id)

  return (
    <SidebarGroup>
      {/* <SidebarGroupLabel>Platform</SidebarGroupLabel> */}
      <SidebarMenu>
        {items.map((item) => {
            if (item.items) {
                return (
                    <Collapsible
                        key={item.title}
                        asChild
                        open={isCollapsibleOpen(item.url)}
                        className="group/collapsible"
                        onOpenChange={(open: boolean) => {
                          if (open) {
                            setOpenCollapsibles((prev: Set<string>) => new Set([...prev, item.url]))
                          } else {
                            setOpenCollapsibles((prev: Set<string>) => {
                              const next = new Set(prev)
                              next.delete(item.url)
                              return next
                            })
                          }
                        }}
                    >
                        <SidebarMenuItem>
                        <CollapsibleTrigger asChild>
                            <SidebarMenuButton tooltip={item.title}>
                            {item.icon && <item.icon />}
                            <span>{item.title}</span>
                            <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
                            </SidebarMenuButton>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                            <SidebarMenuSub>
                            {item.items?.map((subItem) => (
                                <SidebarMenuSubItem key={subItem.title}>
                                <SidebarMenuSubButton asChild>
                                    <Link href={subItem.url}>
                                    <span>{subItem.title}</span>
                                    </Link>
                                </SidebarMenuSubButton>
                                </SidebarMenuSubItem>
                            ))}
                            </SidebarMenuSub>
                        </CollapsibleContent>
                        </SidebarMenuItem>
                    </Collapsible>
                )
            }
            return (
                <SidebarMenuItem key={item.title} >
                  <SidebarMenuButton asChild isActive={isItemActive(item.url)}>
                    <Link href={item.url}>
                      {item.icon && <item.icon />}
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
            )
        }
        )}
      </SidebarMenu>
    </SidebarGroup>
  )
}
