"use client"

import { useEffect, useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { NavSection } from "../../MainLayout";
import { AnimatePresence, motion } from "framer-motion";
import NavLink from "../NavLink";

interface CollapsNavProps {
    data: NavSection;
    activeSection: string | null;
    setActiveSection: (id: string | null) => void;
}

export default function CollapsNav({ data, activeSection, setActiveSection }: CollapsNavProps) {
    const [isFirstRender, setIsFirstRender] = useState(true);

    useEffect(() => {
        setIsFirstRender(false);
    }, []);

    const isActive = activeSection === data.id;

    return (
        <div className="ml-[10px]">
            <div 
                className="flex items-center justify-between w-full cursor-pointer text-[12px] pb-[8px]"
                onClick={() => setActiveSection(isActive ? null : data.id)}
            >
                <div className="flex items-center gap-[8px]">
                    {data.icon}
                    {data.section}
                </div>
                
                <ChevronDownIcon 
                    className={`h-4 w-4 transition-transform duration-300 ${isActive ? "rotate-180" : ""}`} 
                    aria-hidden 
                />
            </div>
            <AnimatePresence>
                {isActive && (
                    <motion.div
                        initial={isFirstRender ? false : { opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.3 }}
                        className="overflow-hidden pl-[10px] border-l border-primary flex flex-col gap-[4px]"
                    >
                        {data.items.map((item, index) => (
                            <NavLink key={`menu-item-${index}`} link={item.href} text={item.label} icon={item.icon} />
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}