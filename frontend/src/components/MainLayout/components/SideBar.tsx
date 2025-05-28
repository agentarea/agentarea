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
import { motion, AnimatePresence } from 'framer-motion';
import { useEffect } from 'react';

type SideBarProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
    initialCollapsed?: boolean;
    initialExpanded?: string[];
}

export default function SideBar({ menuContent, bottomMenuContent, initialCollapsed = false, initialExpanded = [] }: SideBarProps) {
    const t = useTranslations('Sidebar');
    const [isCollapsed, setIsCollapsed] = useState(initialCollapsed);
    const [expandedItems, setExpandedItems] = useState<string[]>(initialExpanded ?? []);
    const [isFirstRender, setIsFirstRender] = useState(true);

    useEffect(() => {
        setIsFirstRender(false);
    }, []);

    const handleToggle = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        setCookie('sidebarCollapsed', newState.toString());
    };

    const handleExpandSection = (sectionName: string) => {
        let newExpandedItems;
        if (expandedItems.includes(sectionName)) {
            newExpandedItems = expandedItems.filter(item => item !== sectionName);
        } else {
            newExpandedItems = [...expandedItems, sectionName];
        }
        setExpandedItems(newExpandedItems);
        setCookie('expandedSections', JSON.stringify(newExpandedItems));
    };

    return (
        <div 
            className={`
                h-screen
                px-[12px] py-[20px] 
                hidden flex-shrink-0 md:flex md:flex-col
                relative
                transition-all duration-300 ease-in-out
                border-r border-zinc-200 dark:border-zinc-700
                ${isCollapsed ? 'w-[65px]' : 'w-[230px]'}
            `}
        >
            <div className="h-[45px] pt-[6px]">
                <div className={cn(
                    "w-full transition-all duration-500 overflow-hidden",
                    isCollapsed ? 'h-[37px]' : 'h-[30px]'
                )}>
                    <LogoIcon />
                </div>
            </div>
            <nav className="overflow-y-auto overflow-x-hidden flex flex-col justify-between h-full gap-[10px]">
                <div>
                    {menuContent.map((sectionContent, index) => (
                        <div key={`section-${index}`} className="flex flex-col gap-[2px] pt-[10px]">
                            {
                                sectionContent.section && (
                                    <SectionTitle 
                                        expanded={expandedItems.includes(sectionContent.section ?? '')}
                                        key={`section-title-${index}`} 
                                        isCollapsed={sectionContent.isCollapsed} 
                                        onClick={() => {
                                            const sectionName = sectionContent.section;
                                            if (sectionName) {
                                                handleExpandSection(sectionName);
                                            }
                                        }}
                                    >
                                        {sectionContent.labelKey ? t(sectionContent.labelKey) : sectionContent.section}
                                    </SectionTitle>
                                )
                            }
                            {
                                sectionContent.isCollapsed ? (
                                    <AnimatePresence>
                                        { expandedItems.includes(sectionContent.section ?? '') && (
                                            <motion.div
                                                initial={isFirstRender ? false : { opacity: 0, height: 0 }}
                                                animate={{ opacity: 1, height: "auto" }}
                                                exit={{ opacity: 0, height: 0 }}
                                                transition={{ duration: 0.3 }}
                                                className="overflow-hidden flex flex-col gap-[2px]"
                                            >
                                                {
                                                    sectionContent.items.map((item, itemIndex) => (
                                                        <NavLink 
                                                            key={`menu-item-${sectionContent.id}-${itemIndex}`} 
                                                            link={item.href} 
                                                            text={item.labelKey ? t(item.labelKey) : item.label}
                                                            icon={item.icon} 
                                                            isCollapsed={isCollapsed}
                                                        />
                                                    ))
                                                }
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                )
                                : (
                                    sectionContent.items.map((item, itemIndex) => (
                                        <NavLink 
                                            key={`menu-item-${sectionContent.id}-${itemIndex}`} 
                                            link={item.href} 
                                            text={item.labelKey ? t(item.labelKey) : item.label}
                                            icon={item.icon} 
                                            isCollapsed={isCollapsed}
                                        />
                                    ))
                                )
                            }
                            <div 
                                className={cn(
                                    "overflow-hidden transition-all duration-500 ease-in-out",
                                    (!sectionContent.isCollapsed || expandedItems.includes(sectionContent.section ?? '')) 
                                        ? "max-h-screen"
                                        : "max-h-0"
                                )}
                            >
                                
                            </div>
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