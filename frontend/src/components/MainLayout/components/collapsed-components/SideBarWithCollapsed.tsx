"use client"

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { NavSection } from "../../MainLayout";
import NavLink from "../NavLink";
import LogoIcon from "../LogoIcon";
import CollapsNav from "./CollapsNav";

type SideBarWithCollapsedProps = {
    menuContent: NavSection[];
}

const getActiveSectionFromPath = (pathname: string, menuContent: NavSection[]): string | null => {
    const currentSection = menuContent.find(section => 
        section.items.some(item => item.href === pathname)
    );
    return currentSection?.id || null;
};

export default function SideBarWithCollapsed({ menuContent }: SideBarWithCollapsedProps) {
    const pathname = usePathname();
    const [activeSection, setActiveSection] = useState<string | null>(
        () => getActiveSectionFromPath(pathname, menuContent)
    );

    // Проверяем URL только при первом рендере
    useEffect(() => {
        const currentSectionId = getActiveSectionFromPath(pathname, menuContent);
        setActiveSection(currentSectionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []); // Пустой массив зависимостей означает, что эффект выполнится только при монтировании

    return (
        <div 
            className="
                h-screen w-[225px]
                px-[16px] py-[18px] 
                hidden flex-shrink-0 md:flex md:flex-col 
                bg-zinc-100 dark:bg-zinc-800 
            "
        >
            <div className="w-full h-[30px]"><LogoIcon/></div>
            <nav className="overflow-y-auto overflow-x-hidden flex flex-col gap-[10px]">
                {
                    menuContent.map((sectionContent, index) => {
                        if (sectionContent.section) {
                            return (
                                    <CollapsNav data={sectionContent} key={`section-title-${index}`} activeSection={activeSection} setActiveSection={setActiveSection} />
                                // <Accordion type="single" collapsible key={`section-title-${index}`}>
                                //     <AccordionItem value="item-1">
                                //         <AccordionTrigger className="flex items-center justify-between w-full">
                                //             {sectionContent.section}
                                //             <ChevronDownIcon className="AccordionChevron h-4 w-4" aria-hidden />
                                //         </AccordionTrigger>
                                //         <AccordionContent>
                                //             {
                                //                 sectionContent.items.map((item, index) => (
                                //                     <NavLink 
                                //                         key={`menu-item-${index}`} 
                                //                         link={item.href} 
                                //                         text={item.label} 
                                //                         icon={item.icon} 
                                //                     />
                                //                 ))
                                //             }
                                //         </AccordionContent>
                                //     </AccordionItem>
                                // </Accordion>
                            )
                        }

                        return sectionContent.items.map((item, index) => (
                            <NavLink 
                                key={`menu-item-${index}`} 
                                link={item.href} 
                                text={item.label} 
                                icon={item.icon} 
                            />
                        ))
                    })
                }
                {/* {menuContent.map((sectionContent, index) => (
                    <div key={`section-${index}`} className="flex flex-col gap-[2px] pt-[14px]">
                        {
                            sectionContent.section && (
                                <SectionTitle key={`section-title-${index}`}>{sectionContent.section}</SectionTitle>
                            )
                        }
                        {
                            sectionContent.items.map((item, index) => (
                                <NavLink 
                                    key={`menu-item-${index}`} 
                                    link={item.href} 
                                    text={item.label} 
                                    icon={item.icon} 
                                />
                            ))
                        }
                    </div>
                ))} */}
            </nav>
        </div>
    )
}