import { NavSection, BottomNavContent } from "../MainLayout";
import NavLink from "./NavLink";
import SectionTitle from "./SectionTitle";
import UserBlock from "./UserBlock";   
import LogoIcon from "./LogoIcon";
import {useTranslations} from 'next-intl';

type SideBarProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
}

export default function SideBar({ menuContent, bottomMenuContent }: SideBarProps) {
    const t = useTranslations('Sidebar');

    return (
        <div 
            className="
                h-screen w-[225px]
                px-[18px] py-[20px] 
                hidden flex-shrink-0 md:flex md:flex-col        
            "
        >
            <div className="w-full h-[30px] mb-[15px] mt-[15px]"><LogoIcon/></div>
            <nav className="overflow-y-auto overflow-x-hidden flex flex-col justify-between h-full gap-[10px]">
                <div>
                    {menuContent.map((sectionContent, index) => (
                        <div key={`section-${index}`} className="flex flex-col gap-[2px] pt-[14px]">
                            {
                                sectionContent.section && (
                                    <SectionTitle key={`section-title-${index}`}>{sectionContent.labelKey ? t(sectionContent.labelKey) : sectionContent.section}</SectionTitle>
                                )
                            }
                            {
                                sectionContent.items.map((item, index) => (
                                    <NavLink 
                                        key={`menu-item-${index}`} 
                                        link={item.href} 
                                        text={item.labelKey ? t(item.labelKey) : item.label} 
                                        icon={item.icon} 
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
                            />
                        ))
                    }

                    <div className="h-[1px] mt-[12px] w-full bg-zinc-200/50 dark:bg-zinc-700" />
                    <UserBlock user={bottomMenuContent.user} />
                </div>
            </nav>
        </div>
    )
}