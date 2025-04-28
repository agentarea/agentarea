import { NavSection, BottomNavContent } from "../MainLayout";
import NavLink from "./NavLink";
import SectionTitle from "./SectionTitle";
import LogoIcon from "./LogoIcon";
import UserBlock from "./UserBlock";   
import { Button } from "@/components/ui/button";
import { Menu } from "lucide-react";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useTranslations } from "next-intl";
import LanguageSelect from "./LanguageSelect";

type HeaderProps = {
    menuContent: NavSection[];
    bottomMenuContent: BottomNavContent;
}

export default function Header({ menuContent, bottomMenuContent }: HeaderProps) {
    const t = useTranslations('Sidebar');
    return (
        <header 
            className="
                h-[50px] w-full
                px-[16px]
                flex flex-row items-center justify-between md:hidden
                bg-zinc-100 dark:bg-zinc-800 
            "
        >
            <Sheet>
                <div className="w-full h-[27px]"><LogoIcon/></div>
                <SheetTrigger asChild>
                    <Button size="icon" variant="ghost" className="h-[25px] w-[25px]">
                        <Menu className="h-[20px] w-[20px]"/>
                        <span className="sr-only">Toggle Menu</span>
                    </Button>
                </SheetTrigger>

                <SheetContent side="left" >
                    <SheetTitle className="hidden">Sidebar</SheetTitle>
                    <nav className="overflow-y-auto overflow-x-hidden flex flex-col h-full gap-[10px]">
                        <div className="flex flex-col gap-[4px]">
                            <UserBlock user={bottomMenuContent.user} />
                            <div className="h-[1px]  w-full bg-zinc-200/50 dark:bg-zinc-700" />
                        </div>
                        <div>
                            {[...menuContent, bottomMenuContent].map((sectionContent, index) => (
                                <div key={`section-${index}`} className="flex flex-col gap-[2px] pt-[14px]">
                                    {
                                        sectionContent.section && (
                                            <SectionTitle key={`section-title-${index}`}>{sectionContent.labelKey ? t(sectionContent.labelKey) : sectionContent.section}</SectionTitle>
                                        )
                                    }
                                    {
                                        sectionContent.items.map((item, index) => (
                                            <SheetClose key={`menu-item-${index}`} asChild>
                                                <NavLink 
                                                    link={item.href} 
                                                    text={item.labelKey ? t(item.labelKey) : item.label} 
                                                    icon={item.icon} 
                                                />
                                            </SheetClose>
                                        ))
                                    }
                                </div>
                            ))}
                            {/* TODO: remove to settings */}
                            <LanguageSelect />
                        </div>
                    </nav>
                </SheetContent>
            </Sheet>
        </header>



    )
}