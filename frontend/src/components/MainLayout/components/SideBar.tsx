import { NavSection, BottomNavContent } from "../MainLayout";
import NavLink from "./NavLink";
import SectionTitle from "./SectionTitle";
import UserBlock from "./UserBlock";   
import LogoIcon from "./LogoIcon";
type SideBarProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
}

export default function SideBar({ menuContent, bottomMenuContent }: SideBarProps) {
    return (
        <div 
            className="
                h-screen w-[250px]
                px-[18px] py-[20px] 
                hidden flex-shrink-0 md:flex md:flex-col 
                bg-[#F4F4F6] dark:bg-neutral-800 
            "
        >
            <div className="w-full h-[30px] mb-[18px]"><LogoIcon/></div>
            <nav className="overflow-y-auto overflow-x-hidden flex flex-col justify-between h-full gap-[10px]">
                <div>
                    {menuContent.map((sectionContent, index) => (
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
                    ))}
                </div>
                <div className="flex flex-col gap-[4px]">
                    {
                        bottomMenuContent.items.map((item, index) => (
                            <NavLink 
                                key={`menu-item-${index}`} 
                                link={item.href} 
                                text={item.label} 
                                icon={item.icon} 
                            />
                        ))
                    }
                    <div className="h-[1px] mt-[12px] w-full bg-neutral-200/50 dark:bg-neutral-700" />
                    <UserBlock user={bottomMenuContent.user} />
                </div>
            </nav>
        </div>
    )
}