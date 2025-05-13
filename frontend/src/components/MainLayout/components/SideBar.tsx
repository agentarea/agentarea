"use client"

import { NavSection, BottomNavContent } from "../MainLayout";
import NavLink from "./NavLink";
import SectionTitle from "./SectionTitle";
import UserBlock from "./UserBlock";   
import LogoIcon from "./LogoIcon";
import { useTranslations } from 'next-intl';
import { useState } from 'react';
import { setCookie } from '@/utils/cookies';
import SidebarToggle from './SidebarToggle';
import { cn } from '@/lib/utils';

type SideBarProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
    initialCollapsed?: boolean;
}

export default function SideBar({ menuContent, bottomMenuContent, initialCollapsed = false }: SideBarProps) {
    const t = useTranslations('Sidebar');
    const [isCollapsed, setIsCollapsed] = useState(initialCollapsed);

    const handleToggle = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        setCookie('sidebarCollapsed', newState.toString());
    };

    return (
        <div 
            className={`
                h-screen
                px-[18px] py-[20px] 
                hidden flex-shrink-0 md:flex md:flex-col
                relative
                transition-all duration-300 ease-in-out
                ${isCollapsed ? 'w-[75px]' : 'w-[225px]'}
            `}
        >
            <div className="h-[70px] pt-[15px]">
                <div className={cn(
                    "w-full transition-all duration-500 overflow-hidden",
                    isCollapsed ? 'h-[38px]' : 'h-[30px]'
                )}>
                    <LogoIcon />
                </div>
            </div>
            <nav className="overflow-y-auto overflow-x-hidden flex flex-col justify-between h-full gap-[10px]">
                <div>
                    {menuContent.map((sectionContent, index) => (
                        <div key={`section-${index}`} className="flex flex-col gap-[2px] pt-[14px]">
                            {
                                sectionContent.section && !isCollapsed && (
                                    <SectionTitle key={`section-title-${index}`}>
                                        {sectionContent.labelKey ? t(sectionContent.labelKey) : sectionContent.section}
                                    </SectionTitle>
                                )
                            }
                            {
                                sectionContent.items.map((item, index) => (
                                    <NavLink 
                                        key={`menu-item-${index}`} 
                                        link={item.href} 
                                        text={item.labelKey ? t(item.labelKey) : item.label}
                                        icon={item.icon} 
                                        isCollapsed={isCollapsed}
                                    />
                                ))
                            }
                        </div>
                    ))}
                </div>
                <div className="flex flex-col gap-[4px]">
                    {
                        bottomMenuContent.items.map((item, index) => (
                            <NavLink 
                                key={`menu-item-${index}`} 
                                link={item.href} 
                                text={item.labelKey ? t(item.labelKey) : item.label}
                                icon={item.icon}
                                isCollapsed={isCollapsed}
                            />
                        ))
                    }

                    <div className="h-[1px] mt-[12px] w-full bg-zinc-200/50 dark:bg-zinc-700" />
                    <UserBlock user={bottomMenuContent.user} isCollapsed={isCollapsed} />
                </div>
            </nav>
            <SidebarToggle isCollapsed={isCollapsed} onToggle={handleToggle} />
        </div>
    );
}